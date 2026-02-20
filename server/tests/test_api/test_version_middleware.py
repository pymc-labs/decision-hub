"""Tests for the CLI version enforcement middleware."""


class TestVersionMiddleware:
    def test_old_version_returns_426(self, test_app, client):
        """Requests from outdated CLI versions get a 426 response."""
        test_app.state.settings.min_cli_version = "0.2.0"

        resp = client.get(
            "/v1/orgs",
            headers={"X-DHub-Client-Version": "0.1.3"},
        )

        assert resp.status_code == 426
        detail = resp.json()["detail"]
        assert "0.1.3" in detail
        assert "0.2.0" in detail

    def test_missing_version_header_passes_through(self, test_app, client):
        """Requests without a version header pass through (browsers, frontend)."""
        test_app.state.settings.min_cli_version = "0.2.0"

        resp = client.get("/v1/orgs")

        # Missing header = not a CLI request; middleware should not block it.
        assert resp.status_code != 426

    def test_valid_version_passes_through(self, test_app, client, auth_headers):
        """A current CLI version should pass the middleware."""
        test_app.state.settings.min_cli_version = "0.2.0"

        resp = client.get(
            "/v1/orgs",
            headers={**auth_headers, "X-DHub-Client-Version": "0.2.0"},
        )

        # Should pass middleware (may get another status from the route itself)
        assert resp.status_code != 426

    def test_newer_version_passes_through(self, test_app, client, auth_headers):
        """A newer CLI version should pass the middleware."""
        test_app.state.settings.min_cli_version = "0.2.0"

        resp = client.get(
            "/v1/orgs",
            headers={**auth_headers, "X-DHub-Client-Version": "0.3.0"},
        )

        assert resp.status_code != 426

    def test_no_enforcement_when_min_version_empty(self, test_app, client, auth_headers):
        """When min_cli_version is empty, all requests pass through."""
        test_app.state.settings.min_cli_version = ""

        resp = client.get(
            "/v1/orgs",
            headers=auth_headers,
        )

        # Should not be 426
        assert resp.status_code != 426

    def test_non_v1_routes_bypass_middleware(self, test_app, client):
        """Non-/v1/ routes should never get a 426."""
        test_app.state.settings.min_cli_version = "99.0.0"

        # The auth route may fail internally (missing GitHub config etc.)
        # but the middleware should not intercept it with a 426.
        resp = client.get("/docs")

        assert resp.status_code != 426
