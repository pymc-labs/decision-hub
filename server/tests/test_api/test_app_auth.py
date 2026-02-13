"""Tests that write endpoints always require authentication.

Verifies the fix for issue #99: authentication on write routers must be
unconditional — it must NOT depend on whether ``require_github_org`` is set.
Each write endpoint declares its own ``Depends(get_current_user)`` parameter,
and the router-level dependency provides defense-in-depth.
"""

from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from decision_hub.api.deps import get_current_user
from decision_hub.api.keys_routes import router as keys_router
from decision_hub.api.org_routes import org_router
from decision_hub.api.registry_routes import router as registry_router
from decision_hub.api.tracker_routes import router as tracker_router


def _make_app(require_github_org: str = "") -> FastAPI:
    """Build a minimal app that mirrors create_app() auth wiring.

    The routers are mounted with the same unconditional auth dependency
    that create_app() applies.  ``require_github_org`` is passed through
    to settings so we can prove it has no effect on authentication.
    """
    settings = MagicMock()
    settings.jwt_secret = "test-secret"
    settings.jwt_algorithm = "HS256"
    settings.jwt_expiry_hours = 1
    settings.fernet_key = Fernet.generate_key().decode()
    settings.github_client_id = "test"
    settings.s3_bucket = "test-bucket"
    settings.google_api_key = ""
    settings.require_github_org = require_github_org
    settings.required_github_orgs = (
        [o.strip() for o in require_github_org.split(",") if o.strip()] if require_github_org else []
    )
    settings.min_cli_version = ""
    settings.list_skills_rate_limit = 30
    settings.list_skills_rate_window = 60
    settings.resolve_rate_limit = 30
    settings.resolve_rate_window = 60
    settings.download_rate_limit = 10
    settings.download_rate_window = 60

    app = FastAPI()
    app.state.settings = settings
    app.state.engine = MagicMock()
    app.state.s3_client = MagicMock()

    # Mirror the unconditional auth wiring from create_app()
    write_deps = [Depends(get_current_user)]
    app.include_router(org_router, dependencies=write_deps)
    app.include_router(registry_router, dependencies=write_deps)
    app.include_router(keys_router, dependencies=write_deps)
    app.include_router(tracker_router, dependencies=write_deps)

    return app


# Representative write endpoints — one from each protected router.
# Payloads are minimally valid so FastAPI doesn't reject with 422 (body
# validation) before the auth dependency has a chance to fire.
_WRITE_ENDPOINTS = [
    ("POST", "/v1/orgs", {"slug": "test-org"}),
    ("POST", "/v1/keys", {"key_name": "test-key", "value": "test-value"}),
    ("DELETE", "/v1/skills/test-org/test-skill/1.0.0", None),
    ("POST", "/v1/trackers", {"repo_url": "https://github.com/example/repo"}),
]


class TestWriteEndpointsRequireAuth:
    """Write endpoints must return 401 without a JWT, regardless of settings."""

    @pytest.mark.parametrize(
        "method,path,json_body",
        _WRITE_ENDPOINTS,
        ids=[ep[1] for ep in _WRITE_ENDPOINTS],
    )
    def test_unauthenticated_rejected_when_org_empty(
        self,
        method: str,
        path: str,
        json_body: dict | None,
    ) -> None:
        """Auth is enforced even when require_github_org is empty (default)."""
        app = _make_app(require_github_org="")
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.request(method, path, json=json_body)

        assert resp.status_code == 401, (
            f"{method} {path} returned {resp.status_code} without auth (require_github_org=''). Expected 401."
        )

    @pytest.mark.parametrize(
        "method,path,json_body",
        _WRITE_ENDPOINTS,
        ids=[ep[1] for ep in _WRITE_ENDPOINTS],
    )
    def test_unauthenticated_rejected_when_org_set(
        self,
        method: str,
        path: str,
        json_body: dict | None,
    ) -> None:
        """Auth is also enforced when require_github_org is set."""
        app = _make_app(require_github_org="pymc-labs")
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.request(method, path, json=json_body)

        assert resp.status_code == 401, (
            f"{method} {path} returned {resp.status_code} without auth (require_github_org='pymc-labs'). Expected 401."
        )
