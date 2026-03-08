"""
Tests for DynatraceClient.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from unittest.mock import MagicMock, patch
from downdetector_monitor.monitor import DynatraceClient, ServiceMetrics


@pytest.fixture
def client():
    return DynatraceClient(
        url="https://test.live.dynatrace.com",
        api_token="dt0c01.testtoken"
    )


@pytest.fixture
def sample_metrics():
    return ServiceMetrics(
        service_name="pix",
        feedback_problems=0,
        percentages={"transferencias": 52, "pagamentos": 31},
        processing_time=42.5,
        success=True,
    )


class TestDynatraceClient:

    def test_endpoint_constructed_correctly(self, client):
        assert client.endpoint == "https://test.live.dynatrace.com/api/v2/metrics/ingest"

    def test_trailing_slash_stripped(self):
        c = DynatraceClient("https://test.live.dynatrace.com/", "token")
        assert not c.endpoint.startswith("https://test.live.dynatrace.com//")

    def test_send_metric_success(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 202

        with patch.object(client.session, "post", return_value=mock_response):
            result = client.send_metric("custom.test.metric", 1)
            assert result is True

    def test_send_metric_bad_request(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Invalid metric"

        with patch.object(client.session, "post", return_value=mock_response):
            result = client.send_metric("custom.test.metric", 1)
            assert result is False

    def test_send_metric_with_dimensions(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 202

        with patch.object(client.session, "post", return_value=mock_response) as mock_post:
            client.send_metric("custom.test", 42, dimensions={"env": "prod"})
            call_data = mock_post.call_args[1]["data"].decode()
            assert "env=prod" in call_data

    def test_send_service_metrics_returns_count(self, client, sample_metrics):
        mock_response = MagicMock()
        mock_response.status_code = 202

        with patch.object(client.session, "post", return_value=mock_response):
            count = client.send_service_metrics(sample_metrics)
            # feedback_problems + 2 percentages + processing_time = 4 metrics
            assert count == 4

    def test_send_metric_network_error(self, client):
        import requests
        with patch.object(client.session, "post", side_effect=requests.RequestException("timeout")):
            result = client.send_metric("custom.test", 1)
            assert result is False

    def test_close_session(self, client):
        with patch.object(client.session, "close") as mock_close:
            client.close()
            mock_close.assert_called_once()
