"""Tests that unmatched /v1/ paths return JSON 404, not SPA HTML.

Verifies the fix for the bug where the SPA catch-all route intercepted
API paths, returning index.html instead of a proper JSON error response.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from decision_hub.api.app import create_app


def _make_client(*, with_frontend: bool = True) -> TestClient:
    """Build a TestClient from the real app factory with mocked infra.

    When *with_frontend* is True a temporary directory with a dummy
    ``index.html`` and ``assets/`` is used so the SPA catch-all is
    registered — matching the production deployment layout.
    """
    settings = MagicMock()
    settings.jwt_secret = "test-secret"
    settings.jwt_algorithm = "HS256"
    settings.jwt_expiry_hours = 1
    settings.fernet_key = Fernet.generate_key().decode()
    settings.github_client_id = "test"
    settings.s3_bucket = "test-bucket"
    settings.google_api_key = ""
    settings.require_github_org = ""
    settings.required_github_orgs = []
    settings.min_cli_version = ""
    settings.log_level = "WARNING"
    settings.database_url = "sqlite://"
    settings.aws_region = "us-east-1"
    settings.aws_access_key_id = "test"
    settings.aws_secret_access_key = "test"
    settings.s3_endpoint_url = None
    settings.latest_cli_version = "0.1.0"
    # Rate limiting
    settings.search_rate_limit = 10
    settings.search_rate_window = 60
    settings.list_skills_rate_limit = 30
    settings.list_skills_rate_window = 60
    settings.resolve_rate_limit = 30
    settings.resolve_rate_window = 60
    settings.download_rate_limit = 10
    settings.download_rate_window = 60
    settings.audit_log_rate_limit = 30
    settings.audit_log_rate_window = 60

    patches = [
        patch("decision_hub.api.app.create_settings", return_value=settings),
        patch("decision_hub.api.app.create_engine", return_value=MagicMock()),
        patch("decision_hub.api.app.create_s3_client", return_value=MagicMock()),
        patch("decision_hub.api.app.setup_logging"),
    ]

    if with_frontend:
        tmp = tempfile.mkdtemp()
        frontend_dir = Path(tmp)
        (frontend_dir / "index.html").write_text("<html><body>SPA</body></html>")
        (frontend_dir / "assets").mkdir()
        (frontend_dir / "vite.svg").write_text("<svg/>")
        patches.append(
            patch("decision_hub.api.app._FRONTEND_DIR", frontend_dir),
        )
    else:
        patches.append(
            patch("decision_hub.api.app._FRONTEND_DIR", Path("/nonexistent")),
        )

    for p in patches:
        p.start()
    try:
        app = create_app()
    finally:
        for p in patches:
            p.stop()

    return TestClient(app, raise_server_exceptions=False)


class TestApiCatchallReturnsJson:
    """Unmatched /v1/ paths must return JSON 404, not SPA HTML."""

    def test_nonexistent_v1_path_returns_json_404(self) -> None:
        client = _make_client()
        resp = client.get("/v1/nonexistent")
        assert resp.status_code == 404
        body = resp.json()
        assert "API endpoint not found" in body["detail"]

    def test_nonexistent_v1_nested_path_returns_json_404(self) -> None:
        client = _make_client()
        resp = client.get("/v1/some/deeply/nested/path")
        assert resp.status_code == 404
        body = resp.json()
        assert "API endpoint not found" in body["detail"]

    def test_bare_v1_returns_json_404(self) -> None:
        client = _make_client()
        resp = client.get("/v1")
        assert resp.status_code == 404
        body = resp.json()
        assert "API endpoint not found" in body["detail"]

    def test_non_v1_path_returns_spa_html(self) -> None:
        """Non-API paths should still serve the SPA index.html."""
        client = _make_client()
        resp = client.get("/some/frontend/route")
        assert resp.status_code == 200
        assert "SPA" in resp.text

    def test_existing_api_route_still_works(self) -> None:
        """Verify that the catch-all doesn't shadow real API endpoints."""
        client = _make_client()
        resp = client.get("/cli/latest-version")
        assert resp.status_code == 200
        assert "latest_version" in resp.json()

    def test_method_not_allowed_preserved(self) -> None:
        """POST to a GET-only endpoint must return 405, not 404.

        Regression test for the bug where a multi-method catch-all route
        converted 405 Method Not Allowed into 404 Not Found.
        """
        client = _make_client()
        resp = client.post("/cli/latest-version")
        assert resp.status_code == 405
