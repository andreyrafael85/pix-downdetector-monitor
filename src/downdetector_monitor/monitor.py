#!/usr/bin/env python3
"""
Downdetector Multi-Service Monitor v3.1
Bright Data Scraping Browser + Dynatrace Metrics Integration

CHANGES v3.1 (hotfix):
- BUGFIX CRÍTICO: falha de conexão/timeout no browser NÃO gera mais
  feedback_problems=1. A métrica só muda quando a página é lida com sucesso.
  Em falha de infraestrutura, feedback_problems é omitido (skip) e apenas
  collection_success=0 é enviado ao Dynatrace — separando claramente
  "serviço com problema" de "coleta falhou".
- Retry automático de conexão com o browser (MAX_BROWSER_RETRIES).
- Novo campo ServiceMetrics.collection_error_type para categorizar a falha
  (browser_timeout | page_error | unknown) como dimensão no Dynatrace.

CHANGES v3.0:
- Correção de falsos positivos via detecção contextual no elemento DOM correto
- Padrões compilados movidos para módulo-level (evita recompilação a cada chamada)
- unicodedata.normalize para normalização robusta de slugs
- Novo check: health_score agregado por serviço
- Tratamento de erro granular com tipos de exceção específicos
- Logging estruturado com contexto de serviço
- Conformidade PEP 8: nomes, espaçamento, comprimento de linha
- Documentação de módulo, classes e funções padronizada (Google Style)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

import requests
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Environment variables with validation
AUTH = os.getenv("AUTH", "brd-customer-xxxxxxxxxxxxx:xxxxxxxxxxxxxx")
DT_URL = os.getenv("DT_URL", "https://xxxxx.live.dynatrace.com")
DT_API_TOKEN = os.getenv("DT_API_TOKEN", "dt0c01.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")


SCREENSHOT_DIR = Path("/tmp/downdetector")

# Timeouts (ms para Playwright, s para asyncio/requests)
CAPTCHA_TIMEOUT_MS: int = 60_000
PAGE_TIMEOUT_MS: int = 180_000
LOAD_TIMEOUT_MS: int = 120_000
SELECTOR_TIMEOUT_MS: int = 60_000
DYNATRACE_TIMEOUT_S: int = 10
HUMAN_SIM_DELAY_S: int = 3
SERVICE_DELAY_S: int = 5
CAPTCHA_RETRY_SLEEP_S: int = 5
FALLBACK_SLEEP_S: int = 30
MAX_BROWSER_RETRIES: int = 2  # tentativas de conexão CDP antes de desistir
BROWSER_RETRY_SLEEP_S: int = 10

# Seletor CSS que contém o status textual principal do serviço
STATUS_SELECTOR: str = "#company-status > div:nth-child(1) > div.desktop-only > div"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PHRASE PATTERNS  (compilados uma única vez no import)
# ---------------------------------------------------------------------------

_RAW_NO_PROBLEMS: Tuple[str, ...] = (
    # "relatos de usuários indicam que não há problemas"
    r"relatos?\s+de\s+usu[aá]rios?\s+indicam?\s+que\s+n[aã]o\s+h[aá]\s+problemas?",
    # "relatórios de usuários indicam nenhum problema"
    r"relat[oó]rios?\s+de\s+usu[aá]rios?\s+indicam?\s+nenhum\s+problema",
    # variações genéricas
    r"n[aã]o\s+h[aá]\s+problemas?\s+atuais?",
    r"nenhum\s+problema\s+atual",
    r"sem\s+problemas?\s+no\s+momento",
    r"tudo\s+funcionando",
    r"servi[cç]o\s+normal",
    r"sem\s+incidentes?",
)

_RAW_PROBLEMS: Tuple[str, ...] = (
    r"usu[aá]rios?\s+est[aã]o\s+reportando\s+problemas?",
    r"problemas?\s+sendo\s+reportados?",
    r"incidente\s+em\s+andamento",
    r"interrup[cç][aã]o\s+detectada",
    r"fora\s+do\s+ar",
    r"indispon[ií]vel",
)

_FLAGS = re.IGNORECASE | re.UNICODE

NO_PROBLEMS_PATTERNS: Tuple[re.Pattern, ...] = tuple(
    re.compile(p, _FLAGS) for p in _RAW_NO_PROBLEMS
)
PROBLEMS_PATTERNS: Tuple[re.Pattern, ...] = tuple(re.compile(p, _FLAGS) for p in _RAW_PROBLEMS)

# ---------------------------------------------------------------------------
# DATA MODELS
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ServiceConfig:
    """Configuração imutável de um serviço a monitorar.

    Args:
        name: Identificador do serviço (usado em nomes de métrica).
        url: URL da página no Downdetector.
        percentage_keywords: Palavras-chave para extração de percentuais.
    """

    name: str
    url: str
    percentage_keywords: Tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.name or not self.url:
            raise ValueError("'name' e 'url' são obrigatórios.")
        if not self.url.startswith(("http://", "https://")):
            raise ValueError(f"URL inválida: {self.url!r}")


class DetectionResult(NamedTuple):
    """Resultado da análise de status do serviço.

    Attributes:
        has_no_problems: True quando o serviço está operacional.
        method: Estratégia que produziu o resultado.
        confidence: Confiança do resultado (0.0–1.0).
        matched_text: Trecho que disparou a detecção, se disponível.
    """

    has_no_problems: bool
    method: str
    confidence: float
    matched_text: Optional[str] = None


@dataclass
class ServiceMetrics:
    """Métricas coletadas de um serviço.

    Attributes:
        service_name: Nome do serviço.
        feedback_problems: 0 = OK, 1 = com problemas, -1 = coleta falhou
            (não enviado ao Dynatrace como indicador de problema do serviço).
        percentages: Mapa slug → valor percentual.
        processing_time_s: Tempo total de coleta em segundos.
        success: True se a coleta foi bem-sucedida.
        detection: Detalhe da detecção de status.
        error: Mensagem de erro, se houver.
        collection_error_type: Categoria da falha de coleta, se aplicável.
            Valores: "browser_timeout" | "page_error" | None.
    """

    service_name: str
    feedback_problems: int  # -1 = não determinado (coleta falhou)
    percentages: Dict[str, int]
    processing_time_s: float
    success: bool
    detection: Optional[DetectionResult] = None
    error: Optional[str] = None
    collection_error_type: Optional[str] = None  # novo: categoriza a falha

    @property
    def health_score(self) -> int:
        """Score de saúde agregado (0–100).

        Retorna -1 quando a coleta falhou (não é possível inferir saúde).
        Penaliza problemas detectados e baixa confiança na detecção.
        Útil como métrica única de observabilidade.
        """
        if not self.success:
            return -1  # coleta falhou; sem inferência
        base = 100 - (self.feedback_problems * 50)
        if self.detection:
            base -= int((1.0 - self.detection.confidence) * 50)
        return max(0, base)


# ---------------------------------------------------------------------------
# SERVICE DEFINITIONS
# ---------------------------------------------------------------------------

SERVICES: Tuple[ServiceConfig, ...] = (
    ServiceConfig(
        name="pix",
        url="https://downdetector.com.br/fora-do-ar/pix/",
        percentage_keywords=(
            "transferências",
            "pagamentos",
            "código qr",
            "Website",
            "Compras",
            "Login",
            "Aplicativo Móvel",
        ),
    ),
    ServiceConfig(
        name="bradesco",
        url="https://downdetector.com.br/fora-do-ar/bradesco/",
        percentage_keywords=(
            "PIX Pessoa Física",
            "Bradesco Net Empresa",
            "Aplicativo Pessoa Física",
        ),
    ),
    ServiceConfig(
        name="itau",
        url="https://downdetector.com.br/fora-do-ar/banco-itau/",
        percentage_keywords=(
            "Login no aplicativo móvel",
            "Operações no internet banking",
            "PIX",
        ),
    ),
)

# ---------------------------------------------------------------------------
# UTILITY FUNCTIONS
# ---------------------------------------------------------------------------


def normalize_slug(keyword: str) -> str:
    """Converte keyword em slug seguro para nomes de métrica.

    Usa unicodedata.normalize (NFKD) para remover acentos de forma canônica,
    mais robusto do que substituição manual caractere a caractere.

    Args:
        keyword: Texto original (pode conter acentos e espaços).

    Returns:
        Slug em lowercase com apenas [a-z0-9_].

    Examples:
        >>> normalize_slug("Aplicativo Móvel")
        'aplicativo_movel'
    """
    normalized = unicodedata.normalize("NFKD", keyword.lower())
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text)
    return slug.strip("_")


def validate_environment() -> Tuple[bool, List[str]]:
    """Verifica se as variáveis de ambiente obrigatórias estão configuradas.

    Returns:
        Tupla (válido, lista_de_erros).
    """
    checks = {
        "AUTH": (AUTH, "xxxxx"),
        "DT_URL": (DT_URL, "xxxxx"),
        "DT_API_TOKEN": (DT_API_TOKEN, "xxxxx"),
    }
    errors = [
        f"{var} não configurado (contém placeholder)"
        for var, (value, placeholder) in checks.items()
        if placeholder in value
    ]
    if not DT_URL.startswith("https://"):
        errors.append("DT_URL deve começar com 'https://'")
    return not errors, errors


# ---------------------------------------------------------------------------
# STATUS DETECTION
# ---------------------------------------------------------------------------


def detect_status(element_text: str) -> DetectionResult:
    """Detecta o status do serviço a partir do texto do elemento DOM correto.

    Aplica três estratégias em ordem de confiança decrescente:

    1. Regex ``NO_PROBLEMS_PATTERNS`` → sem problemas (confiança 0.95).
    2. Regex ``PROBLEMS_PATTERNS``    → com problemas (confiança 0.95).
    3. Contagem de palavras-chave positivas vs. negativas (confiança 0.70).

    A detecção é feita sobre o texto do seletor CSS ``STATUS_SELECTOR``
    (elemento DOM específico), não sobre o body inteiro, eliminando falsos
    positivos causados por frases em outras seções da página.

    Args:
        element_text: Texto extraído do elemento de status (lowercase).

    Returns:
        DetectionResult com o resultado e metadados da detecção.
    """
    # Estratégia 1 – padrão "sem problemas"
    for pattern in NO_PROBLEMS_PATTERNS:
        match = pattern.search(element_text)
        if match:
            logger.debug("   ✅ Regex NO_PROBLEMS: %s", pattern.pattern[:60])
            return DetectionResult(
                has_no_problems=True,
                method="regex_no_problems",
                confidence=0.95,
                matched_text=match.group(0),
            )

    # Estratégia 2 – padrão "com problemas"
    for pattern in PROBLEMS_PATTERNS:
        match = pattern.search(element_text)
        if match:
            logger.debug("   ⚠️  Regex PROBLEMS: %s", pattern.pattern[:60])
            return DetectionResult(
                has_no_problems=False,
                method="regex_problems",
                confidence=0.95,
                matched_text=match.group(0),
            )

    # Estratégia 3 – contagem de palavras-chave
    positive_kws = ("não há problemas", "nenhum problema", "sem problemas", "tudo funcionando")
    negative_kws = ("reportando problemas", "fora do ar", "indisponível", "interrupção")

    pos = sum(1 for kw in positive_kws if kw in element_text)
    neg = sum(1 for kw in negative_kws if kw in element_text)

    if pos != neg:
        no_problems = pos > neg
        logger.debug("   🔎 Keyword fuzzy: pos=%d neg=%d → %s", pos, neg, no_problems)
        return DetectionResult(
            has_no_problems=no_problems,
            method="keyword_fuzzy",
            confidence=0.70,
            matched_text=f"pos={pos}, neg={neg}",
        )

    # Nenhum padrão encontrado – assume problemas com confiança baixa
    logger.warning("   ❌ Nenhum padrão encontrado; assumindo problemas.")
    return DetectionResult(
        has_no_problems=False,
        method="no_match_default",
        confidence=0.50,
    )


# ---------------------------------------------------------------------------
# DYNATRACE CLIENT
# ---------------------------------------------------------------------------


class DynatraceClient:
    """Envia métricas para o Dynatrace Metrics Ingestion API v2.

    Args:
        url: URL base do ambiente Dynatrace (ex.: https://abc.live.dynatrace.com).
        api_token: Token de API com permissão ``metrics.ingest``.
    """

    _METRIC_PREFIX = "custom.downdetector"

    def __init__(self, url: str, api_token: str) -> None:
        self._endpoint = f"{url.rstrip('/')}/api/v2/metrics/ingest"
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Api-Token {api_token}",
                "Content-Type": "text/plain; charset=utf-8",
            }
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send_service_metrics(self, metrics: ServiceMetrics) -> int:
        """Envia todas as métricas de um serviço para o Dynatrace.

        Métricas sempre enviadas:
        - ``collection_success``: 1 (coleta OK) ou 0 (falha de coleta).
        - ``processing_time_ms``: tempo de coleta em milissegundos.

        Métricas enviadas SOMENTE quando a coleta foi bem-sucedida:
        - ``feedback_problems``: 0 (sem problemas) ou 1 (com problemas).
          **Nunca enviada em caso de falha de coleta**, evitando falsos
          positivos quando o problema é de infraestrutura de monitoramento.
        - ``health_score``: score agregado 0–100.
        - ``detection_confidence``: confiança da detecção (0–100).
        - ``<keyword>_pct``: percentual por categoria de relato.

        Args:
            metrics: Objeto com as métricas coletadas do serviço.

        Returns:
            Número de métricas enviadas com sucesso.
        """
        svc = metrics.service_name

        # Métricas de infraestrutura — sempre enviadas
        to_send: Dict[str, int] = {
            f"{self._METRIC_PREFIX}.{svc}_collection_success": int(metrics.success),
            f"{self._METRIC_PREFIX}.{svc}_processing_time_ms": int(
                metrics.processing_time_s * 1_000
            ),
        }

        if metrics.success:
            # Métricas de status do serviço — SOMENTE quando a coleta funcionou
            to_send[f"{self._METRIC_PREFIX}.{svc}_feedback_problems"] = metrics.feedback_problems
            if metrics.health_score >= 0:
                to_send[f"{self._METRIC_PREFIX}.{svc}_health_score"] = metrics.health_score
            if metrics.detection:
                to_send[f"{self._METRIC_PREFIX}.{svc}_detection_confidence"] = int(
                    metrics.detection.confidence * 100
                )
            for keyword, pct in metrics.percentages.items():
                to_send[f"{self._METRIC_PREFIX}.{svc}_{keyword}_pct"] = pct
        else:
            logger.warning(
                "   ⚠️  Coleta falhou (%s) — feedback_problems NÃO enviado ao Dynatrace.",
                metrics.collection_error_type or "unknown",
            )

        success_count = sum(self._send_metric(name, value) for name, value in to_send.items())
        logger.info("📤 Enviadas %d/%d métricas para '%s'", success_count, len(to_send), svc)
        return success_count

    def close(self) -> None:
        """Fecha a sessão HTTP."""
        self._session.close()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _send_metric(self, metric_name: str, value: int) -> bool:
        """Envia uma métrica individual.

        Args:
            metric_name: Nome completo da métrica.
            value: Valor inteiro da métrica.

        Returns:
            True se o envio foi aceito (HTTP 202).
        """
        payload = f"{metric_name},source=downdetector {value}"
        try:
            response = self._session.post(
                self._endpoint,
                data=payload.encode("utf-8"),
                timeout=DYNATRACE_TIMEOUT_S,
            )
        except requests.Timeout:
            logger.error("❌ Timeout ao enviar métrica: %s", metric_name)
            return False
        except requests.ConnectionError as exc:
            logger.error("❌ Erro de conexão ao enviar %s: %s", metric_name, exc)
            return False
        except requests.RequestException as exc:
            logger.error("❌ Erro inesperado ao enviar %s: %s", metric_name, exc)
            return False

        if response.status_code == 202:
            logger.debug("✅ Métrica aceita: %s=%d", metric_name, value)
            return True

        logger.warning(
            "⚠️  Status %d ao enviar '%s': %s",
            response.status_code,
            metric_name,
            response.text[:200],
        )
        return False


# ---------------------------------------------------------------------------
# BROWSER AUTOMATION
# ---------------------------------------------------------------------------


class DowndetectorMonitor:
    """Coleta métricas do Downdetector via Bright Data Scraping Browser.

    Args:
        auth: Credencial no formato ``brd-customer-xxx:token``.
    """

    def __init__(self, auth: str) -> None:
        self._endpoint_url = f"wss://{auth}@brd.superproxy.io:9222"
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def monitor_service(self, service: ServiceConfig) -> ServiceMetrics:
        """Navega até a página do serviço e extrai métricas.

        Tenta conectar ao browser CDP até MAX_BROWSER_RETRIES vezes.
        Em caso de falha de conexão/timeout, retorna ServiceMetrics com
        ``success=False`` e ``feedback_problems=-1`` — garantindo que
        nenhum falso positivo de "serviço com problema" seja enviado ao
        Dynatrace quando o erro é de infraestrutura de coleta.

        Args:
            service: Configuração do serviço a monitorar.

        Returns:
            ServiceMetrics populado com os dados coletados.
        """
        start = time.monotonic()
        logger.info("\n%s", "=" * 60)
        logger.info("🔍 Monitorando: %s", service.name.upper())
        logger.info("🌐 URL: %s", service.url)

        last_error = ""
        for attempt in range(1, MAX_BROWSER_RETRIES + 1):
            browser: Optional[Browser] = None
            try:
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.connect_over_cdp(self._endpoint_url)
                    context = await browser.new_context()
                    return await self._collect(service, context, start)

            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.warning(
                    "   ⚠️  Falha de conexão (tentativa %d/%d): %s",
                    attempt,
                    MAX_BROWSER_RETRIES,
                    exc,
                )
                if attempt < MAX_BROWSER_RETRIES:
                    logger.info(
                        "   🔄 Aguardando %ds antes de nova tentativa…",
                        BROWSER_RETRY_SLEEP_S,
                    )
                    await asyncio.sleep(BROWSER_RETRY_SLEEP_S)
            finally:
                if browser:
                    try:
                        await browser.close()
                    except Exception:  # noqa: BLE001
                        pass

        # Todas as tentativas esgotadas — falha de infraestrutura
        logger.error(
            "❌ Coleta falhou após %d tentativas para '%s': %s",
            MAX_BROWSER_RETRIES,
            service.name,
            last_error,
        )
        # feedback_problems=-1 sinaliza "não determinado" — NÃO é problema
        # do serviço monitorado, é falha na coleta.
        return ServiceMetrics(
            service_name=service.name,
            feedback_problems=-1,  # ← nunca envia como problema real
            percentages={},
            processing_time_s=time.monotonic() - start,
            success=False,
            error=last_error,
            collection_error_type="browser_timeout",
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _collect(
        self,
        service: ServiceConfig,
        context: BrowserContext,
        start: float,
    ) -> ServiceMetrics:
        """Executa a coleta em uma aba do browser.

        Args:
            service: Configuração do serviço.
            context: Contexto do Playwright já criado.
            start: Timestamp de início (monotonic).

        Returns:
            ServiceMetrics com os dados coletados ou falha.
        """
        page = await context.new_page()
        try:
            await page.goto(service.url, timeout=PAGE_TIMEOUT_MS)
            await self._handle_captcha(page)
            await self._wait_for_content(page)
            await self._simulate_human(page)

            # Extrai status do elemento DOM correto (evita falsos positivos)
            status_text = await self._get_status_element_text(page)
            detection = detect_status(status_text)
            feedback_problems = 0 if detection.has_no_problems else 1

            level = logger.info if detection.has_no_problems else logger.warning
            level(
                "   %s Status: %s (método=%s, confiança=%.0f%%)",
                "✅" if detection.has_no_problems else "⚠️",
                "Sem problemas" if detection.has_no_problems else "Com problemas",
                detection.method,
                detection.confidence * 100,
            )

            # Extrai percentuais do body completo
            body_text = (await page.inner_text("body")).lower()
            percentages = self._extract_percentages(body_text, service.percentage_keywords)

            return ServiceMetrics(
                service_name=service.name,
                feedback_problems=feedback_problems,
                percentages=percentages,
                processing_time_s=time.monotonic() - start,
                success=True,
                detection=detection,
            )

        except Exception as exc:  # noqa: BLE001
            logger.error("❌ Erro monitorando '%s': %s", service.name, exc)
            await self._screenshot(page, f"{service.name}_error")
            return ServiceMetrics(
                service_name=service.name,
                feedback_problems=-1,  # ← falha de coleta, não do serviço
                percentages={},
                processing_time_s=time.monotonic() - start,
                success=False,
                error=str(exc),
                collection_error_type="page_error",
            )

        finally:
            await page.close()
            await context.close()

    async def _get_status_element_text(self, page: Page) -> str:
        """Extrai o texto do elemento de status principal.

        Usar o seletor CSS específico em vez do body inteiro elimina
        falsos positivos causados por frases em rodapés, comentários
        de usuários ou outras seções da página.

        Args:
            page: Aba do Playwright.

        Returns:
            Texto do elemento em lowercase, ou string vazia se não encontrado.
        """
        try:
            element = await page.wait_for_selector(
                STATUS_SELECTOR,
                timeout=SELECTOR_TIMEOUT_MS,
            )
            if element:
                text = await element.inner_text()
                logger.debug("   📋 Texto do elemento de status: %r", text[:120])
                return text.lower()
        except Exception as exc:  # noqa: BLE001
            logger.warning("   ⚠️  Elemento de status não encontrado: %s", exc)
        return ""

    async def _handle_captcha(self, page: Page, retries: int = 2) -> bool:
        """Aguarda a resolução do CAPTCHA pelo Bright Data.

        Args:
            page: Aba do Playwright.
            retries: Número máximo de tentativas.

        Returns:
            True se o CAPTCHA foi resolvido.
        """
        for attempt in range(retries):
            try:
                client = await page.context.new_cdp_session(page)
                result = await client.send(
                    "Captcha.waitForSolve",
                    {"detectTimeout": CAPTCHA_TIMEOUT_MS},
                )
                status = result.get("status", "unknown")
                logger.info("   CAPTCHA: %s (tentativa %d/%d)", status, attempt + 1, retries)
                if status == "solve_finished":
                    return True
                if attempt < retries - 1:
                    await asyncio.sleep(CAPTCHA_RETRY_SLEEP_S)
            except Exception as exc:  # noqa: BLE001
                logger.warning("   Erro no CAPTCHA (tentativa %d): %s", attempt + 1, exc)
                if attempt < retries - 1:
                    await asyncio.sleep(CAPTCHA_RETRY_SLEEP_S)
        return False

    async def _wait_for_content(self, page: Page) -> None:
        """Aguarda o carregamento da página com fallback por sleep.

        Args:
            page: Aba do Playwright.
        """
        try:
            await page.wait_for_load_state("load", timeout=LOAD_TIMEOUT_MS)
            await page.wait_for_selector("body", timeout=SELECTOR_TIMEOUT_MS)
            logger.debug("   ✅ Página carregada.")
        except Exception:  # noqa: BLE001
            logger.warning("   ⚠️  Timeout no load state; aguardando %ds.", FALLBACK_SLEEP_S)
            await asyncio.sleep(FALLBACK_SLEEP_S)

    async def _simulate_human(self, page: Page) -> None:
        """Simula comportamento humano para contornar detecção de bots.

        Args:
            page: Aba do Playwright.
        """
        try:
            await page.evaluate("window.scrollBy(0, 500)")
            await asyncio.sleep(HUMAN_SIM_DELAY_S)
            await page.mouse.move(300, 400)
            await asyncio.sleep(HUMAN_SIM_DELAY_S)
            logger.debug("   👤 Comportamento humano simulado.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("   Falha na simulação humana: %s", exc)

    @staticmethod
    def _extract_percentages(text: str, keywords: Tuple[str, ...]) -> Dict[str, int]:
        """Extrai percentuais associados às palavras-chave.

        O padrão busca ``<N>% <keyword>`` no texto (case-insensitive via lowercase).

        Args:
            text: Texto da página em lowercase.
            keywords: Palavras-chave dos tipos de relato.

        Returns:
            Dicionário {slug: percentual}.
        """
        return {
            normalize_slug(kw): int(match.group(1))
            for kw in keywords
            if (match := re.search(rf"(\d+)%\s*{re.escape(kw.lower())}", text))
        }

    async def _screenshot(self, page: Page, name: str) -> None:
        """Salva screenshot para debug.

        Args:
            page: Aba do Playwright.
            name: Prefixo do arquivo.
        """
        try:
            path = SCREENSHOT_DIR / f"{name}_{int(time.time())}.png"
            await page.screenshot(path=str(path))
            logger.debug("📸 Screenshot salvo: %s", path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Falha ao salvar screenshot '%s': %s", name, exc)

    @staticmethod
    def _failure_metrics(name: str, start: float, error: str) -> ServiceMetrics:
        """Cria um ServiceMetrics de falha padronizado.

        Args:
            name: Nome do serviço.
            start: Timestamp de início.
            error: Mensagem de erro.

        Returns:
            ServiceMetrics com success=False.
        """


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


async def main() -> None:
    """Ponto de entrada principal: valida ambiente, coleta e envia métricas."""
    logger.info("=" * 60)
    logger.info("🚀 Downdetector Multi-Service Monitor v3.1")
    logger.info("=" * 60)

    is_valid, errors = validate_environment()
    if not is_valid:
        logger.error("❌ Variáveis de ambiente inválidas:")
        for err in errors:
            logger.error("   - %s", err)
        sys.exit(1)

    logger.info("✅ Ambiente validado | Serviços: %d", len(SERVICES))

    dynatrace = DynatraceClient(DT_URL, DT_API_TOKEN)
    monitor = DowndetectorMonitor(AUTH)
    results: List[ServiceMetrics] = []

    try:
        for idx, service in enumerate(SERVICES):
            metrics = await monitor.monitor_service(service)
            results.append(metrics)
            dynatrace.send_service_metrics(metrics)

            if idx < len(SERVICES) - 1:
                logger.info("\n⏳ Aguardando %ds antes do próximo serviço…", SERVICE_DELAY_S)
                await asyncio.sleep(SERVICE_DELAY_S)

        _print_summary(results)

    except KeyboardInterrupt:
        logger.warning("\n⚠️  Interrompido pelo usuário.")
    except Exception as exc:  # noqa: BLE001
        logger.error("❌ Erro inesperado: %s", exc)
        sys.exit(1)
    finally:
        dynatrace.close()


def _print_summary(results: List[ServiceMetrics]) -> None:
    """Imprime o resumo final da execução.

    Args:
        results: Lista de métricas coletadas.
    """
    successful = sum(1 for r in results if r.success)
    logger.info("\n%s", "=" * 60)
    logger.info("📊 RESUMO")
    logger.info("=" * 60)
    logger.info(
        "✅ Sucesso: %d/%d | ❌ Falha: %d/%d",
        successful,
        len(results),
        len(results) - successful,
        len(results),
    )

    for result in results:
        if result.success:
            problem_icon = "🔴" if result.feedback_problems else "🟢"
            problems_str = f"problemas={result.feedback_problems}"
            score_str = f"score={result.health_score}"
        else:
            problem_icon = "⚪"  # cinza = coleta falhou, status desconhecido
            problems_str = "problemas=N/A (coleta falhou)"
            score_str = f"erro={result.collection_error_type or 'unknown'}"

        confidence_str = (
            f", confiança={result.detection.confidence:.0%}" if result.detection else ""
        )
        logger.info(
            "%s %s: %s %s | métricas=%d | %s | tempo=%.1fs%s",
            "✅" if result.success else "❌",
            result.service_name,
            problem_icon,
            problems_str,
            len(result.percentages),
            score_str,
            result.processing_time_s,
            confidence_str,
        )

    logger.info("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 Encerrando…")
        sys.exit(0)
