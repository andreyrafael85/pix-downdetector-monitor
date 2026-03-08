"""
Tests for utility functions.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from downdetector_monitor.monitor import normalize_slug, validate_environment


class TestNormalizeSlug:
    """Tests for normalize_slug function."""

    def test_simple_lowercase(self):
        assert normalize_slug("login") == "login"

    def test_spaces_to_underscore(self):
        assert normalize_slug("PIX Pessoa Física") == "pix_pessoa_fisica"

    def test_portuguese_accents(self):
        assert normalize_slug("transferências") == "transferencias"
        assert normalize_slug("código qr") == "codigo_qr"
        assert normalize_slug("pagamentos") == "pagamentos"

    def test_uppercase(self):
        assert normalize_slug("APLICATIVO MÓVEL") == "aplicativo_movel"

    def test_multiple_spaces(self):
        result = normalize_slug("login  no  app")
        assert "__" not in result

    def test_special_chars_replaced(self):
        result = normalize_slug("pix@banco!")
        assert "@" not in result
        assert "!" not in result

    def test_leading_trailing_underscores_stripped(self):
        result = normalize_slug(" pix ")
        assert not result.startswith("_")
        assert not result.endswith("_")


class TestValidateEnvironment:
    """Tests for validate_environment function."""

    def test_invalid_when_placeholders_present(self, monkeypatch):
        monkeypatch.setenv("AUTH", "brd-customer-xxxxxxxxxxxxx:xxxxxxxxxxxxxx")
        monkeypatch.setenv("DT_URL", "https://xxxxx.live.dynatrace.com")
        monkeypatch.setenv("DT_API_TOKEN", "dt0c01.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")

        # Reload module to pick up new env vars
        import importlib
        import downdetector_monitor.monitor as m
        m.AUTH = os.getenv("AUTH", "brd-customer-xxxxxxxxxxxxx:xxxxxxxxxxxxxx")
        m.DT_URL = os.getenv("DT_URL", "https://xxxxx.live.dynatrace.com")
        m.DT_API_TOKEN = os.getenv("DT_API_TOKEN", "dt0c01.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")

        is_valid, errors = validate_environment()
        assert not is_valid
        assert len(errors) > 0

    def test_returns_tuple(self):
        result = validate_environment()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], list)
