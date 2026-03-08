"""
Tests for DowndetectorMonitor and data models.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from downdetector_monitor.monitor import (
    ServiceConfig,
    ServiceMetrics,
    DowndetectorMonitor,
    SERVICES,
)


class TestServiceConfig:

    def test_valid_service_config(self):
        svc = ServiceConfig(
            name="pix",
            url="https://downdetector.com.br/fora-do-ar/pix/",
            expected_phrase="relatos de usuários",
            percentage_keywords=["transferências", "pagamentos"],
        )
        assert svc.name == "pix"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Invalid URL"):
            ServiceConfig(
                name="pix",
                url="not-a-url",
                expected_phrase="relatos",
                percentage_keywords=[],
            )

    def test_empty_name_raises(self):
        with pytest.raises(ValueError):
            ServiceConfig(
                name="",
                url="https://example.com",
                expected_phrase="test",
                percentage_keywords=[],
            )


class TestServiceMetrics:

    def test_defaults_success(self):
        m = ServiceMetrics(
            service_name="pix",
            feedback_problems=0,
            percentages={},
            processing_time=1.0,
            success=True,
        )
        assert m.error is None

    def test_failed_metric_has_error(self):
        m = ServiceMetrics(
            service_name="pix",
            feedback_problems=1,
            percentages={},
            processing_time=0.5,
            success=False,
            error="Connection timeout",
        )
        assert m.error == "Connection timeout"
        assert m.feedback_problems == 1


class TestServicesDefinition:

    def test_services_not_empty(self):
        assert len(SERVICES) >= 1

    def test_all_services_have_required_fields(self):
        for svc in SERVICES:
            assert svc.name
            assert svc.url.startswith("https://")
            assert svc.expected_phrase
            assert isinstance(svc.percentage_keywords, list)

    def test_pix_service_present(self):
        names = [s.name for s in SERVICES]
        assert "pix" in names


class TestExtractPercentages:

    def setup_method(self):
        self.monitor = DowndetectorMonitor(auth="brd-test:test")

    def test_extracts_single_percentage(self):
        text = "52% transferências foram reportados"
        result = self.monitor.extract_percentages(text, ["transferências"])
        assert result.get("transferencias") == 52

    def test_extracts_multiple_percentages(self):
        text = "31% pagamentos, 17% código qr, 52% transferências"
        keywords = ["pagamentos", "código qr", "transferências"]
        result = self.monitor.extract_percentages(text, keywords)
        assert result["pagamentos"] == 31
        assert result["codigo_qr"] == 17
        assert result["transferencias"] == 52

    def test_missing_keyword_not_in_result(self):
        text = "52% transferências"
        result = self.monitor.extract_percentages(text, ["login"])
        assert "login" not in result

    def test_empty_text_returns_empty_dict(self):
        result = self.monitor.extract_percentages("", ["transferências"])
        assert result == {}
