#!/usr/bin/env python3
"""
Downdetector Multi-Service Monitor - Production Ready v2.0
Bright Data Scraping Browser + Dynatrace Metrics Integration

NEW FEATURES v2.0:
- Robust pattern matching for text variations
- Multiple validation strategies
- Intelligent phrase detection with fuzzy matching
- Enhanced error reporting
"""

import asyncio
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

import requests
from playwright.async_api import Browser, Page, async_playwright

# ============================================================================
# CONFIGURATION
# ============================================================================
# Environment variables with validation
AUTH = os.getenv('AUTH', 'brd-customer-xxxxxxxxxxxxx:xxxxxxxxxxxxxx')
DT_URL = os.getenv('DT_URL', 'https://xxxxx.live.dynatrace.com')
DT_API_TOKEN = os.getenv('DT_API_TOKEN', 'dt0c01.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx')

# Constants
SCREENSHOT_DIR = Path("/tmp/downdetector")
CAPTCHA_TIMEOUT = 60_000
PAGE_TIMEOUT = 180_000
LOAD_TIMEOUT = 120_000
SELECTOR_TIMEOUT = 60_000
HUMAN_SIM_DELAY = 3
SERVICE_DELAY = 5

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# PATTERN DEFINITIONS
# ============================================================================

class PhrasePatterns:
    """
    Centralized phrase patterns for robust detection.
    Handles text variations across Downdetector updates.
    """
    
    # Padrões que indicam AUSÊNCIA de problemas (status OK)
    NO_PROBLEMS_PATTERNS = [
        # Padrão antigo: "relatos de usuários indicam que não há problemas"
        r'relatos?\s+de\s+usu[aá]rios?\s+indicam?\s+que\s+n[aã]o\s+h[aá]\s+problemas?',
        
        # Padrão novo: "relatórios de usuários indicam nenhum problema"
        r'relat[oó]rios?\s+de\s+usu[aá]rios?\s+indicam?\s+nenhum\s+problema',
        
        # Variações adicionais (case-insensitive via flags)
        r'n[aã]o\s+h[aá]\s+problemas?\s+atuais?',
        r'nenhum\s+problema\s+atual',
        r'sem\s+problemas?\s+no\s+momento',
        r'tudo\s+funcionando',
        r'servi[cç]o\s+normal',
        r'sem\s+incidentes?',
    ]
    
    # Padrões que indicam PRESENÇA de problemas
    PROBLEMS_PATTERNS = [
        r'usu[aá]rios?\s+est[aã]o\s+reportando\s+problemas?',
        r'problemas?\s+sendo\s+reportados?',
        r'incidente\s+em\s+andamento',
        r'interrup[cç][aã]o\s+detectada',
        r'fora\s+do\s+ar',
        r'indispon[ií]vel',
    ]
    
    @classmethod
    def compile_patterns(cls) -> Tuple[List[re.Pattern], List[re.Pattern]]:
        """
        Compile regex patterns for performance.
        
        Returns:
            Tuple of (no_problems_patterns, problems_patterns)
        """
        no_problems = [
            re.compile(pattern, re.IGNORECASE | re.UNICODE)
            for pattern in cls.NO_PROBLEMS_PATTERNS
        ]
        
        problems = [
            re.compile(pattern, re.IGNORECASE | re.UNICODE)
            for pattern in cls.PROBLEMS_PATTERNS
        ]
        
        return no_problems, problems


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ServiceConfig:
    """Configuration for a single service to monitor."""
    name: str
    url: str
    percentage_keywords: List[str]
    
    # Optional: Multiple expected phrases for flexibility
    expected_phrases: List[str] = field(default_factory=list)
    
    def __post_init__(self):
        """Validate service configuration."""
        if not self.name or not self.url:
            raise ValueError("Service name and URL are required")
        if not self.url.startswith(('http://', 'https://')):
            raise ValueError(f"Invalid URL: {self.url}")
        
        # Se expected_phrases estiver vazio, criar lista padrão
        if not self.expected_phrases:
            self.expected_phrases = [
                f"relatos de usuários indicam que não há problemas atuais com {self.name}",
                f"relatórios de usuários indicam nenhum problema atual em {self.name}",
                f"não há problemas atuais com {self.name}",
                f"nenhum problema atual em {self.name}",
            ]


@dataclass
class PhraseDetectionResult:
    """Result of phrase detection analysis."""
    has_no_problems: bool  # True = sem problemas, False = com problemas
    matched_pattern: Optional[str] = None
    detection_method: str = "unknown"
    confidence: float = 0.0  # 0.0 to 1.0


@dataclass
class ServiceMetrics:
    """Metrics collected for a service."""
    service_name: str
    feedback_problems: int
    percentages: Dict[str, int]
    processing_time: float
    success: bool
    detection_result: Optional[PhraseDetectionResult] = None
    error: Optional[str] = None


# ============================================================================
# SERVICE DEFINITIONS
# ============================================================================

SERVICES = [
    ServiceConfig(
        name="pix",
        url="https://downdetector.com.br/fora-do-ar/pix/",
        percentage_keywords=[
            "transferências", "pagamentos", "código qr",
            "Website", "Compras", "Login", "Aplicativo Móvel"
        ]
    ),
    ServiceConfig(
        name="bradesco",
        url="https://downdetector.com.br/fora-do-ar/bradesco/",
        percentage_keywords=[
            "PIX Pessoa Física", "Bradesco Net Empresa",
            "Aplicativo Pessoa Física"
        ]
    ),
    ServiceConfig(
        name="itau",
        url="https://downdetector.com.br/fora-do-ar/banco-itau/",
        percentage_keywords=[
            "Login no aplicativo móvel", "Operações no internet banking", "PIX"
        ]
    ),
]


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def normalize_slug(keyword: str) -> str:
    """
    Normalize keyword to valid metric name slug.
    
    Args:
        keyword: Raw keyword string
        
    Returns:
        Normalized slug safe for metric names
    """
    replacements = {
        'ã': 'a', 'á': 'a', 'à': 'a', 'â': 'a',
        'é': 'e', 'ê': 'e',
        'í': 'i',
        'ó': 'o', 'ô': 'o', 'õ': 'o',
        'ú': 'u', 'ü': 'u',
        'ç': 'c'
    }
    
    keyword_lower = keyword.lower()
    for old, new in replacements.items():
        keyword_lower = keyword_lower.replace(old, new)
    
    slug = keyword_lower.replace(' ', '_')
    slug = re.sub(r'[^a-z0-9_]', '_', slug)
    slug = re.sub(r'_+', '_', slug).strip('_')
    
    return slug


def validate_environment() -> Tuple[bool, List[str]]:
    """Validate required environment variables."""
    errors = []
    
    if 'xxxxx' in AUTH:
        errors.append("AUTH not configured (contains placeholder)")
    
    if 'xxxxx' in DT_URL:
        errors.append("DT_URL not configured (contains placeholder)")
    
    if 'xxxxx' in DT_API_TOKEN:
        errors.append("DT_API_TOKEN not configured (contains placeholder)")
    
    if not DT_URL.startswith('https://'):
        errors.append("DT_URL must start with https://")
    
    return (len(errors) == 0, errors)


def detect_no_problems_phrase(text: str, service_name: str) -> PhraseDetectionResult:
    """
    Intelligent phrase detection with multiple strategies.
    
    Strategies:
    1. Compiled regex patterns (primary)
    2. Exact phrase matching (fallback)
    3. Fuzzy keyword matching (last resort)
    
    Args:
        text: Page text content (lowercase)
        service_name: Service name for context
        
    Returns:
        PhraseDetectionResult with detection details
    """
    # Strategy 1: Compiled regex patterns
    no_problems_patterns, problems_patterns = PhrasePatterns.compile_patterns()
    
    # Check for "NO PROBLEMS" patterns
    for pattern in no_problems_patterns:
        match = pattern.search(text)
        if match:
            logger.debug(f"   ✅ Matched NO PROBLEMS pattern: {pattern.pattern[:50]}...")
            return PhraseDetectionResult(
                has_no_problems=True,
                matched_pattern=match.group(0),
                detection_method="regex_no_problems",
                confidence=0.95
            )
    
    # Check for "PROBLEMS" patterns
    for pattern in problems_patterns:
        match = pattern.search(text)
        if match:
            logger.debug(f"   ⚠️ Matched PROBLEMS pattern: {pattern.pattern[:50]}...")
            return PhraseDetectionResult(
                has_no_problems=False,
                matched_pattern=match.group(0),
                detection_method="regex_problems",
                confidence=0.95
            )
    
    # Strategy 2: Exact phrase matching (case-insensitive)
    exact_phrases_no_problems = [
        f"não há problemas atuais com {service_name}",
        f"nenhum problema atual em {service_name}",
        f"não há problemas com {service_name}",
        f"nenhum problema em {service_name}",
    ]
    
    for phrase in exact_phrases_no_problems:
        if phrase in text:
            logger.debug(f"   ✅ Matched exact phrase: {phrase}")
            return PhraseDetectionResult(
                has_no_problems=True,
                matched_pattern=phrase,
                detection_method="exact_match",
                confidence=0.90
            )
    
    # Strategy 3: Keyword-based detection (fuzzy)
    positive_keywords = ['não há problemas', 'nenhum problema', 'sem problemas', 'tudo funcionando']
    negative_keywords = ['reportando problemas', 'fora do ar', 'indisponível', 'interrupção']
    
    positive_count = sum(1 for kw in positive_keywords if kw in text)
    negative_count = sum(1 for kw in negative_keywords if kw in text)
    
    if positive_count > negative_count:
        logger.debug(f"   ✅ Keyword-based: positive={positive_count}, negative={negative_count}")
        return PhraseDetectionResult(
            has_no_problems=True,
            matched_pattern=f"keywords: {positive_count} positive, {negative_count} negative",
            detection_method="keyword_fuzzy",
            confidence=0.70
        )
    elif negative_count > positive_count:
        logger.debug(f"   ⚠️ Keyword-based: positive={positive_count}, negative={negative_count}")
        return PhraseDetectionResult(
            has_no_problems=False,
            matched_pattern=f"keywords: {positive_count} positive, {negative_count} negative",
            detection_method="keyword_fuzzy",
            confidence=0.70
        )
    
    # Default: Assume problems if nothing matched
    logger.warning(f"   ❌ No pattern matched - assuming problems")
    return PhraseDetectionResult(
        has_no_problems=False,
        matched_pattern=None,
        detection_method="no_match_default",
        confidence=0.50
    )


# ============================================================================
# DYNATRACE INTEGRATION
# ============================================================================

class DynatraceClient:
    """Client for sending metrics to Dynatrace."""
    
    def __init__(self, url: str, api_token: str):
        self.url = url.rstrip('/')
        self.api_token = api_token
        self.endpoint = f"{self.url}/api/v2/metrics/ingest"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Api-Token {self.api_token}",
            "Content-Type": "text/plain; charset=utf-8"
        })
    
    def send_metric(self, metric_name: str, value: int,
                    dimensions: Optional[Dict[str, str]] = None) -> bool:
        """Send a single metric to Dynatrace."""
        try:
            if dimensions:
                dims_str = ','.join(f"{k}={v}" for k, v in dimensions.items())
                metric_line = f"{metric_name},{dims_str} {value}"
            else:
                metric_line = f"{metric_name},source=downdetector {value}"
            
            response = self.session.post(
                self.endpoint,
                data=metric_line.encode('utf-8'),
                timeout=10
            )
            
            if response.status_code == 202:
                logger.debug(f"✅ Metric sent: {metric_name}={value}")
                return True
            elif response.status_code == 400:
                logger.error(f"❌ Invalid metric format: {metric_name}")
                logger.error(f"   Response: {response.text}")
                return False
            else:
                logger.warning(f"⚠️ Unexpected status {response.status_code}: {metric_name}")
                return False
                
        except requests.RequestException as e:
            logger.error(f"❌ Dynatrace API error for {metric_name}: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error sending {metric_name}: {e}")
            return False
    
    def send_service_metrics(self, metrics: ServiceMetrics) -> int:
        """Send all metrics for a service."""
        success_count = 0
        
        # Send feedback_problems metric
        if self.send_metric(
            f"custom.downdetector.{metrics.service_name}_feedback_problems",
            metrics.feedback_problems
        ):
            success_count += 1
        
        # Send detection confidence (NEW)
        if metrics.detection_result and self.send_metric(
            f"custom.downdetector.{metrics.service_name}_detection_confidence",
            int(metrics.detection_result.confidence * 100)
        ):
            success_count += 1
        
        # Send percentage metrics
        for keyword, percentage in metrics.percentages.items():
            metric_name = f"custom.downdetector.{metrics.service_name}_{keyword}_pct"
            if self.send_metric(metric_name, percentage):
                success_count += 1
        
        # Send processing time metric
        if self.send_metric(
            f"custom.downdetector.{metrics.service_name}_processing_time_ms",
            int(metrics.processing_time * 1000)
        ):
            success_count += 1
        
        logger.info(f"📤 Sent {success_count} metrics for {metrics.service_name}")
        return success_count
    
    def close(self):
        """Close the session."""
        self.session.close()


# ============================================================================
# BROWSER AUTOMATION
# ============================================================================

class DowndetectorMonitor:
    """Monitor Downdetector services using Bright Data Scraping Browser."""
    
    def __init__(self, auth: str):
        self.auth = auth
        self.endpoint_url = f'wss://{auth}@brd.superproxy.io:9222'
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    
    async def take_screenshot(self, page: Page, name: str) -> None:
        """Take screenshot for debugging."""
        try:
            path = SCREENSHOT_DIR / f"{name}_{int(time.time())}.png"
            await page.screenshot(path=str(path))
            logger.debug(f"📸 Screenshot saved: {path}")
        except Exception as e:
            logger.warning(f"Failed to save screenshot {name}: {e}")
    
    async def wait_for_captcha(self, page: Page, retries: int = 2) -> bool:
        """Wait for Bright Data to solve CAPTCHA."""
        for attempt in range(retries):
            try:
                client = await page.context.new_cdp_session(page)
                result = await client.send(
                    'Captcha.waitForSolve',
                    {'detectTimeout': CAPTCHA_TIMEOUT}
                )
                
                status = result.get('status', 'unknown')
                logger.info(f"   CAPTCHA status: {status} (attempt {attempt + 1}/{retries})")
                
                if status == 'solve_finished':
                    return True
                
                if attempt < retries - 1:
                    logger.info("   Retrying CAPTCHA...")
                    await asyncio.sleep(5)
                    
            except Exception as e:
                logger.warning(f"   CAPTCHA error (attempt {attempt + 1}): {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(5)
        
        return False
    
    async def wait_for_content(self, page: Page) -> bool:
        """Wait for page content to load with multiple fallback strategies."""
        try:
            await page.wait_for_load_state('load', timeout=LOAD_TIMEOUT)
            await page.wait_for_selector('body', timeout=SELECTOR_TIMEOUT)
            logger.debug("   ✅ Page loaded (load state)")
            return True
        except Exception as e:
            logger.debug(f"   Load state timeout: {e}")
        
        logger.warning("   ⚠️ Using fallback sleep (30s)")
        await asyncio.sleep(30)
        return True
    
    async def simulate_human_behavior(self, page: Page) -> None:
        """Simulate human-like interactions."""
        try:
            await page.evaluate("window.scrollBy(0, 500)")
            await asyncio.sleep(HUMAN_SIM_DELAY)
            await page.mouse.move(300, 400)
            await asyncio.sleep(HUMAN_SIM_DELAY)
            logger.debug("   👤 Human behavior simulated")
        except Exception as e:
            logger.warning(f"   Failed to simulate human behavior: {e}")
    
    def extract_percentages(self, text: str, keywords: List[str]) -> Dict[str, int]:
        """Extract percentage values from text for given keywords."""
        percentages = {}
        
        for keyword in keywords:
            pattern = rf'(\d+)%\s*{re.escape(keyword.lower())}'
            match = re.search(pattern, text)
            
            if match:
                percentage = int(match.group(1))
                slug = normalize_slug(keyword)
                percentages[slug] = percentage
                logger.info(f"   📊 {keyword}: {percentage}%")
            else:
                logger.debug(f"   ⚠️ Keyword not found: {keyword}")
        
        return percentages
    
    async def monitor_service(self, service: ServiceConfig) -> ServiceMetrics:
        """Monitor a single service."""
        start_time = time.time()
        logger.info(f"\n{'='*60}")
        logger.info(f"🔍 Monitoring: {service.name.upper()}")
        logger.info(f"🌐 URL: {service.url}")
        
        browser: Optional[Browser] = None
        
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.connect_over_cdp(self.endpoint_url)
                context = await browser.new_context()
                page = await context.new_page()
                
                try:
                    logger.info("   Loading page...")
                    await page.goto(service.url, timeout=PAGE_TIMEOUT)
                    
                    captcha_solved = await self.wait_for_captcha(page)
                    if not captcha_solved:
                        logger.warning("   ⚠️ CAPTCHA may not have been solved")
                    
                    await self.wait_for_content(page)
                    await self.simulate_human_behavior(page)
                    
                    # Extract text
                    text = await page.inner_text('body')
                    text_lower = text.lower()
                    
                    # NEW: Robust phrase detection
                    detection_result = detect_no_problems_phrase(text_lower, service.name)
                    
                    feedback_problems = 0 if detection_result.has_no_problems else 1
                    
                    # Log detailed detection info
                    if detection_result.has_no_problems:
                        logger.info(f"   ✅ No problems detected")
                    else:
                        logger.warning(f"   ⚠️ Problems detected")
                    
                    logger.info(f"   🔍 Detection: method={detection_result.detection_method}, "
                               f"confidence={detection_result.confidence:.0%}")
                    
                    if detection_result.matched_pattern:
                        logger.debug(f"   📝 Matched: {detection_result.matched_pattern[:80]}...")
                    
                    # Extract percentages
                    percentages = self.extract_percentages(text_lower, service.percentage_keywords)
                    
                    processing_time = time.time() - start_time
                    
                    return ServiceMetrics(
                        service_name=service.name,
                        feedback_problems=feedback_problems,
                        percentages=percentages,
                        processing_time=processing_time,
                        success=True,
                        detection_result=detection_result
                    )
                    
                except Exception as e:
                    logger.error(f"   ❌ Error monitoring {service.name}: {e}")
                    await self.take_screenshot(page, f"{service.name}_error")
                    
                    processing_time = time.time() - start_time
                    return ServiceMetrics(
                        service_name=service.name,
                        feedback_problems=1,
                        percentages={},
                        processing_time=processing_time,
                        success=False,
                        error=str(e)
                    )
                
                finally:
                    await page.close()
                    await context.close()
                    
        except Exception as e:
            logger.error(f"   ❌ Browser connection error: {e}")
            processing_time = time.time() - start_time
            return ServiceMetrics(
                service_name=service.name,
                feedback_problems=1,
                percentages={},
                processing_time=processing_time,
                success=False,
                error=str(e)
            )
        
        finally:
            if browser:
                await browser.close()


# ============================================================================
# MAIN EXECUTION
# ============================================================================

async def main():
    """Main execution function."""
    logger.info("="*60)
    logger.info("🚀 Downdetector Multi-Service Monitor v2.0")
    logger.info("="*60)
    
    is_valid, errors = validate_environment()
    if not is_valid:
        logger.error("❌ Environment validation failed:")
        for error in errors:
            logger.error(f"   - {error}")
        sys.exit(1)
    
    logger.info("✅ Environment validated")
    logger.info(f"📊 Services to monitor: {len(SERVICES)}")
    logger.info("")
    
    dynatrace = DynatraceClient(DT_URL, DT_API_TOKEN)
    monitor = DowndetectorMonitor(AUTH)
    
    results: List[ServiceMetrics] = []
    
    try:
        for service in SERVICES:
            metrics = await monitor.monitor_service(service)
            results.append(metrics)
            
            dynatrace.send_service_metrics(metrics)
            
            if service != SERVICES[-1]:
                logger.info(f"\n⏳ Waiting {SERVICE_DELAY}s before next service...")
                await asyncio.sleep(SERVICE_DELAY)
        
        # Summary
        logger.info("\n" + "="*60)
        logger.info("📊 SUMMARY")
        logger.info("="*60)
        
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful
        
        logger.info(f"✅ Successful: {successful}/{len(results)}")
        logger.info(f"❌ Failed: {failed}/{len(results)}")
        
        for result in results:
            status_emoji = "✅" if result.success else "❌"
            problem_emoji = "🔴" if result.feedback_problems == 1 else "🟢"
            
            confidence_str = ""
            if result.detection_result:
                confidence_str = f", Confidence={result.detection_result.confidence:.0%}"
            
            logger.info(
                f"{status_emoji} {result.service_name}: "
                f"{problem_emoji} Problems={result.feedback_problems}, "
                f"Metrics={len(result.percentages)}, "
                f"Time={result.processing_time:.1f}s{confidence_str}"
            )
        
        logger.info("="*60)
        
    except KeyboardInterrupt:
        logger.warning("\n⚠️ Interrupted by user")
    
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        sys.exit(1)
    
    finally:
        dynatrace.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Exiting...")
        sys.exit(0)
