"""Shared fixtures for API route tests."""

from unittest.mock import MagicMock
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from decision_hub.api.app import _parse_semver
from decision_hub.api.auth_routes import router as auth_router
from decision_hub.api.deps import get_current_user
from decision_hub.api.keys_routes import router as keys_router
from decision_hub.api.org_routes import org_public_router, org_router
from decision_hub.api.registry_routes import public_router as registry_public_router
from decision_hub.api.registry_routes import router as registry_router
from decision_hub.domain.auth import create_jwt


@pytest.fixture
def test_settings() -> MagicMock:
    """Mocked Settings object with all fields needed by routes."""
    settings = MagicMock()
    settings.jwt_secret = "test-jwt-secret-for-api-tests"
    settings.jwt_algorithm = "HS256"
    settings.jwt_expiry_hours = 1
    settings.fernet_key = Fernet.generate_key().decode()
    settings.github_client_id = "test-client-id"
    settings.s3_bucket = "test-bucket"
    settings.google_api_key = ""
    settings.require_github_org = ""
    settings.required_github_orgs = []
    settings.min_cli_version = ""
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
    return settings


@pytest.fixture
def test_app(test_settings: MagicMock) -> FastAPI:
    """Create a FastAPI test app with mocked infrastructure."""
    app = FastAPI()

    app.state.settings = test_settings
    app.state.engine = MagicMock()
    app.state.s3_client = MagicMock()

    @app.middleware("http")
    async def check_cli_version(request: Request, call_next):
        """Reject requests from outdated CLI versions on /v1/ routes.

        Mirrors production CLIVersionMiddleware behaviour: only enforce
        when the header IS present and is outdated. Requests without
        the header (browsers, frontend) pass through.
        """
        if request.url.path.startswith("/v1/"):
            min_ver = test_settings.min_cli_version
            if min_ver:
                client_ver = request.headers.get("X-DHub-Client-Version", "")
                if client_ver and _parse_semver(client_ver) < _parse_semver(min_ver):
                    return JSONResponse(
                        status_code=426,
                        content={
                            "detail": (
                                f"Your CLI version ({client_ver or 'unknown'}) is below the "
                                f"minimum required ({min_ver}). "
                                "Run 'uv tool install --upgrade dhub-cli' or "
                                "'pip install --upgrade dhub-cli' to update."
                            ),
                        },
                    )
        return await call_next(request)

    app.include_router(auth_router)
    app.include_router(org_public_router)
    app.include_router(registry_public_router)

    # Mirror production app.py: write routers get unconditional auth deps
    # as defense-in-depth alongside per-endpoint Depends(get_current_user).
    write_deps = [Depends(get_current_user)]
    app.include_router(org_router, dependencies=write_deps)
    app.include_router(registry_router, dependencies=write_deps)
    app.include_router(keys_router, dependencies=write_deps)

    return app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    """TestClient bound to the test app."""
    return TestClient(test_app)


@pytest.fixture
def auth_headers(test_settings: MagicMock) -> dict[str, str]:
    """Authorization headers containing a valid JWT for the sample user."""
    token = create_jwt(
        user_id="12345678-1234-5678-1234-567812345678",
        username="testuser",
        secret=test_settings.jwt_secret,
        algorithm=test_settings.jwt_algorithm,
        expiry_hours=test_settings.jwt_expiry_hours,
        github_orgs=["test-org"],
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_user_id() -> UUID:
    """The UUID that matches the auth_headers JWT 'sub' claim."""
    return UUID("12345678-1234-5678-1234-567812345678")


