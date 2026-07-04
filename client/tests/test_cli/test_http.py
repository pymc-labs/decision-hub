"""Tests for the shared CLI HTTP client wrapper."""

from unittest.mock import patch

import httpx
import respx

from dhub.cli.http import DEFAULT_TIMEOUT_SECONDS, api_client


class TestApiClient:
    """The api_client context manager centralises base_url, headers, and timeout."""

    @respx.mock
    @patch("dhub.cli.config.get_client_version", return_value="0.9.0")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_get_request_uses_configured_base_url_and_client_version_header(
        self,
        _mock_url,
        _mock_version,
    ) -> None:
        route = respx.get("http://test:8000/v1/keys").mock(return_value=httpx.Response(200, json=[]))

        with api_client() as client:
            resp = client.get("/v1/keys")

        assert resp.status_code == 200
        request = route.calls.last.request
        # X-DHub-Client-Version must be attached on every request.
        assert request.headers["x-dhub-client-version"] == "0.9.0"
        # Anonymous access → no Authorization header.
        assert "authorization" not in request.headers

    @respx.mock
    @patch("dhub.cli.config.get_client_version", return_value="0.9.0")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_attaches_bearer_token_when_provided(
        self,
        _mock_url,
        _mock_version,
    ) -> None:
        route = respx.get("http://test:8000/v1/keys").mock(return_value=httpx.Response(200, json=[]))

        with api_client(token="tok-abc") as client:
            client.get("/v1/keys")

        request = route.calls.last.request
        assert request.headers["authorization"] == "Bearer tok-abc"

    @respx.mock
    @patch("dhub.cli.config.get_client_version", return_value="0.9.0")
    def test_explicit_base_url_overrides_config(
        self,
        _mock_version,
    ) -> None:
        route = respx.get("http://override:9000/health").mock(return_value=httpx.Response(200))

        with api_client(token=None, base_url="http://override:9000") as client:
            resp = client.get("/health")

        assert resp.status_code == 200
        assert route.called

    @patch("dhub.cli.config.get_client_version", return_value="0.9.0")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_default_timeout_is_60_seconds(
        self,
        _mock_url,
        _mock_version,
    ) -> None:
        assert DEFAULT_TIMEOUT_SECONDS == 60.0
        with api_client() as client:
            assert client.timeout.read == 60.0

    @patch("dhub.cli.config.get_client_version", return_value="0.9.0")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_timeout_can_be_overridden(
        self,
        _mock_url,
        _mock_version,
    ) -> None:
        with api_client(timeout=5) as client:
            assert client.timeout.read == 5.0

    @patch("dhub.cli.config.get_client_version", return_value="0.9.0")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000/")
    def test_trailing_slash_is_stripped_from_base_url(
        self,
        _mock_url,
        _mock_version,
    ) -> None:
        """Absolute URLs with a trailing slash on base_url should not double-slash paths."""
        with api_client() as client:
            # httpx's request URL join preserves the leading '/' on the path.
            joined = str(client.build_request("GET", "/v1/keys").url)
        assert joined == "http://test:8000/v1/keys"
