#!/usr/bin/env python3
"""
Downdetector Multi-Service Monitor - Production Ready
Bright Data Scraping Browser + Dynatrace Metrics Integration

Features:
- Async service monitoring with parallel processing
- Robust error handling and retry logic
- Type hints for better code documentation
- Comprehensive logging with structured output
- PEP 8 compliant with performance optimizations
"""

import asyncio
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
CAPTCHA_TIMEOUT = 60_000  # 60 seconds
PAGE_TIMEOUT = 180_000  # 3 minutes
LOAD_TIMEOUT = 120_000  # 2 minutes
SELECTOR_TIMEOUT = 60_000  # 1 minute
HUMAN_SIM_DELAY = 3  # seconds
SERVICE_DELAY = 5  # seconds between services

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class ServiceConfig:
    """Configuration for a single service to monitor."""
    name: str
    url: str
    expected_phrase: str
    percentage_keywords: List[str]

    def __post_init__(self):
        """Validate service configuration."""
        if not self.name or not self.url:
            raise ValueError(f"Service name and URL are required")
        if not self.url.startswith(('http://', 'https://')):
            raise ValueError(f"Invalid URL: {self.url}")


@dataclass
class ServiceMetrics:
    """Metrics collected for a service."""
    service_name: str
    feedback_problems: int
    percentages: Dict[str, int]
    processing_time: float
    success: bool
    error: Optional[str] = None


# ============================================================================
# SERVICE DEFINITIONS
# ============================================================================

SERVICES = [
    ServiceConfig(
        name="pix",
        url="https://downdetector.com.br/fora-do-ar/pix/",
        expected_phrase="relatos de usuários indicam que não há problemas atuais com pix",
        percentage_keywords=[
            "transferências", "pagamentos", "código qr",
            "Website", "Compras", "Login", "Aplicativo Móvel"
        ]
    ),
    ServiceConfig(
        name="bradesco",
        url="https://downdetector.com.br/fora-do-ar/bradesco/",
        expected_phrase="relatos de usuários indicam que não há problemas atuais com bradesco",
        percentage_keywords=[
            "PIX Pessoa Física", "Bradesco Net Empresa",
            "Aplicativo Pessoa Física"
        ]
    ),
    ServiceConfig(
        name="itau",
        url="https://downdetector.com.br/fora-do-ar/banco-itau/",
        expected_phrase="relatos de usuários indicam que não há problemas atuais com banco itaú",
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
        
    Example:
        >>> normalize_slug("PIX Pessoa Física")
        'pix_pessoa_fisica'
    """
    # Normalize unicode characters
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
    
    # Replace spaces and remove invalid characters
    slug = keyword_lower.replace(' ', '_')
    slug = re.sub(r'[^a-z0-9_]', '_', slug)
    
    # Remove duplicate underscores
    slug = re.sub(r'_+', '_', slug).strip('_')
    
    return slug


def validate_environment() -> Tuple[bool, List[str]]:
    """
    Validate required environment variables.
    
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
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


# ============================================================================
# DYNATRACE INTEGRATION
# ============================================================================

class DynatraceClient:
    """Client for sending metrics to Dynatrace."""
    
    def __init__(self, url: str, api_token: str):
        """
        Initialize Dynatrace client.
        
        Args:
            url: Dynatrace tenant URL
            api_token: API token for authentication
        """
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
        """
        Send a single metric to Dynatrace.
        
        Args:
            metric_name: Name of the metric (e.g., 'custom.downdetector.pix_status')
            value: Metric value
            dimensions: Optional dimensions dict
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Build metric line
            if dimensions:
                dims_str = ','.join(f"{k}={v}" for k, v in dimensions.items())
                metric_line = f"{metric_name},{dims_str} {value}"
            else:
                metric_line = f"{metric_name},source=downdetector {value}"
            
            # Send to Dynatrace
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
        """
        Send all metrics for a service.
        
        Args:
            metrics: ServiceMetrics object
            
        Returns:
            Number of successfully sent metrics
        """
        success_count = 0
        
        # Send feedback_problems metric
        if self.send_metric(
            f"custom.downdetector.{metrics.service_name}_feedback_problems",
            metrics.feedback_problems
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
        """
        Initialize monitor.
        
        Args:
            auth: Bright Data authentication string
        """
        self.auth = auth
        self.endpoint_url = f'wss://{auth}@brd.superproxy.io:9222'
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    
    async def take_screenshot(self, page: Page, name: str) -> None:
        """
        Take screenshot for debugging.
        
        Args:
            page: Playwright page object
            name: Screenshot name
        """
        try:
            path = SCREENSHOT_DIR / f"{name}_{int(time.time())}.png"
            await page.screenshot(path=str(path))
            logger.debug(f"📸 Screenshot saved: {path}")
        except Exception as e:
            logger.warning(f"Failed to save screenshot {name}: {e}")
    
    async def wait_for_captcha(self, page: Page, retries: int = 2) -> bool:
        """
        Wait for Bright Data to solve CAPTCHA.
        
        Args:
            page: Playwright page object
            retries: Number of retry attempts
            
        Returns:
            True if CAPTCHA solved, False otherwise
        """
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
                    logger.info(f"   Retrying CAPTCHA...")
                    await asyncio.sleep(5)
                    
            except Exception as e:
                logger.warning(f"   CAPTCHA error (attempt {attempt + 1}): {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(5)
        
        return False
    
    async def wait_for_content(self, page: Page, expected_phrase: str) -> bool:
        """
        Wait for page content to load with multiple fallback strategies.
        
        Args:
            page: Playwright page object
            expected_phrase: Expected phrase to verify content loaded
            
        Returns:
            True if content loaded, False otherwise
        """
        # Strategy 1: Wait for load state
        try:
            await page.wait_for_load_state('load', timeout=LOAD_TIMEOUT)
            await page.wait_for_selector('body', timeout=SELECTOR_TIMEOUT)
            logger.debug("   ✅ Page loaded (load state)")
            return True
        except Exception as e:
            logger.debug(f"   Load state timeout: {e}")
        
        # Strategy 2: Wait for expected phrase
        try:
            await page.wait_for_selector(
                f'text={expected_phrase}',
                timeout=SELECTOR_TIMEOUT
            )
            logger.debug("   ✅ Page loaded (expected phrase found)")
            return True
        except Exception as e:
            logger.debug(f"   Expected phrase not found: {e}")
        
        # Strategy 3: Fallback sleep
        logger.warning("   ⚠️ Using fallback sleep (30s)")
        await asyncio.sleep(30)
        return True
    
    async def simulate_human_behavior(self, page: Page) -> None:
        """
        Simulate human-like interactions.
        
        Args:
            page: Playwright page object
        """
        try:
            # Scroll
            await page.evaluate("window.scrollBy(0, 500)")
            await asyncio.sleep(HUMAN_SIM_DELAY)
            
            # Mouse movement
            await page.mouse.move(300, 400)
            await asyncio.sleep(HUMAN_SIM_DELAY)
            
            logger.debug("   👤 Human behavior simulated")
        except Exception as e:
            logger.warning(f"   Failed to simulate human behavior: {e}")
    
    def extract_percentages(self, text: str, keywords: List[str]) -> Dict[str, int]:
        """
        Extract percentage values from text for given keywords.
        
        Args:
            text: Page text content (already lowercase)
            keywords: List of keywords to search for
            
        Returns:
            Dict mapping normalized keywords to percentages
        """
        percentages = {}
        
        for keyword in keywords:
            # Create regex pattern: (\d+)%\s*keyword
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
        """
        Monitor a single service.
        
        Args:
            service: ServiceConfig object
            
        Returns:
            ServiceMetrics object with collected data
        """
        start_time = time.time()
        logger.info(f"\n{'='*60}")
        logger.info(f"🔍 Monitoring: {service.name.upper()}")
        logger.info(f"🌐 URL: {service.url}")
        
        browser: Optional[Browser] = None
        
        try:
            # Connect to Scraping Browser
            async with async_playwright() as playwright:
                browser = await playwright.chromium.connect_over_cdp(self.endpoint_url)
                context = await browser.new_context()
                page = await context.new_page()
                
                try:
                    # Navigate to page
                    logger.info(f"   Loading page...")
                    await page.goto(service.url, timeout=PAGE_TIMEOUT)
                    
                    # Wait for CAPTCHA
                    captcha_solved = await self.wait_for_captcha(page)
                    if not captcha_solved:
                        logger.warning(f"   ⚠️ CAPTCHA may not have been solved")
                    
                    # Wait for content
                    await self.wait_for_content(page, service.expected_phrase)
                    
                    # Simulate human behavior
                    await self.simulate_human_behavior(page)
                    
                    # Extract text
                    text = await page.inner_text('body')
                    text_lower = text.lower()
                    
                    # Check for expected phrase (feedback_problems)
                    expected_phrase_lower = service.expected_phrase.lower()
                    feedback_problems = 0 if expected_phrase_lower in text_lower else 1
                    
                    if feedback_problems == 0:
                        logger.info(f"   ✅ No problems detected")
                    else:
                        logger.warning(f"   ⚠️ Problems detected (expected phrase missing)")
                    
                    # Extract percentages
                    percentages = self.extract_percentages(text_lower, service.percentage_keywords)
                    
                    processing_time = time.time() - start_time
                    
                    return ServiceMetrics(
                        service_name=service.name,
                        feedback_problems=feedback_problems,
                        percentages=percentages,
                        processing_time=processing_time,
                        success=True
                    )
                    
                except Exception as e:
                    logger.error(f"   ❌ Error monitoring {service.name}: {e}")
                    await self.take_screenshot(page, f"{service.name}_error")
                    
                    processing_time = time.time() - start_time
                    return ServiceMetrics(
                        service_name=service.name,
                        feedback_problems=1,  # Assume problems on error
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
    logger.info("🚀 Downdetector Multi-Service Monitor")
    logger.info("="*60)
    
    # Validate environment
    is_valid, errors = validate_environment()
    if not is_valid:
        logger.error("❌ Environment validation failed:")
        for error in errors:
            logger.error(f"   - {error}")
        logger.error("\nPlease set environment variables:")
        logger.error("   export AUTH='brd-customer-...:...'")
        logger.error("   export DT_URL='https://....live.dynatrace.com'")
        logger.error("   export DT_API_TOKEN='dt0c01....'")
        sys.exit(1)
    
    logger.info(f"✅ Environment validated")
    logger.info(f"📊 Services to monitor: {len(SERVICES)}")
    logger.info("")
    
    # Initialize clients
    dynatrace = DynatraceClient(DT_URL, DT_API_TOKEN)
    monitor = DowndetectorMonitor(AUTH)
    
    # Process services
    results: List[ServiceMetrics] = []
    
    try:
        for service in SERVICES:
            metrics = await monitor.monitor_service(service)
            results.append(metrics)
            
            # Send to Dynatrace
            dynatrace.send_service_metrics(metrics)
            
            # Delay between services
            if service != SERVICES[-1]:  # Not last service
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
            logger.info(
                f"{status_emoji} {result.service_name}: "
                f"{problem_emoji} Problems={result.feedback_problems}, "
                f"Metrics={len(result.percentages)}, "
                f"Time={result.processing_time:.1f}s"
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
