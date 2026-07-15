"""Tests for the SecurityHeadersMiddleware."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from decision_hub.api.app import SecurityHeadersMiddleware


def _make_app() -> FastAPI:
    """Create a minimal FastAPI app with the security headers middleware."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/test")
    def test_endpoint():
        return {"ok": True}

    return app


class TestSecurityHeadersMiddleware:
    def test_x_frame_options_present(self) -> None:
        client = TestClient(_make_app())
        resp = client.get("/test")
        assert resp.headers["x-frame-options"] == "DENY"

    def test_x_content_type_options_present(self) -> None:
        client = TestClient(_make_app())
        resp = client.get("/test")
        assert resp.headers["x-content-type-options"] == "nosniff"

    def test_strict_transport_security_present(self) -> None:
        client = TestClient(_make_app())
        resp = client.get("/test")
        assert resp.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"

    def test_referrer_policy_present(self) -> None:
        """Skill/eval URLs must not leak into third-party analytics via Referer."""
        client = TestClient(_make_app())
        resp = client.get("/test")
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"

    def test_permissions_policy_denies_privileged_features(self) -> None:
        """High-privilege browser features the SPA never needs are disabled."""
        client = TestClient(_make_app())
        resp = client.get("/test")
        policy = resp.headers["permissions-policy"]
        for feature in ("camera", "microphone", "geolocation", "payment", "usb"):
            # Each entry looks like ``feature=()`` — an empty allowlist.
            assert f"{feature}=()" in policy

    def test_headers_on_error_responses(self) -> None:
        """Security headers should appear even on 404 responses."""
        client = TestClient(_make_app())
        resp = client.get("/nonexistent")
        assert resp.status_code == 404
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
        assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "camera=()" in resp.headers["permissions-policy"]
