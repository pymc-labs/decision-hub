"""Shared fixtures for API route tests."""

from unittest.mock import MagicMock
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from decision_hub.api.auth_routes import router as auth_router
from decision_hub.api.keys_routes import router as keys_router
from decision_hub.api.org_routes import invite_router, org_router
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
    return settings


@pytest.fixture
def test_app(test_settings: MagicMock) -> FastAPI:
    """Create a FastAPI test app with mocked infrastructure."""
    app = FastAPI()

    app.state.settings = test_settings
    app.state.engine = MagicMock()
    app.state.s3_client = MagicMock()

    app.include_router(auth_router)
    app.include_router(org_router)
    app.include_router(invite_router)
    app.include_router(registry_router)
    app.include_router(keys_router)

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
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def sample_user_id() -> UUID:
    """The UUID that matches the auth_headers JWT 'sub' claim."""
    return UUID("12345678-1234-5678-1234-567812345678")
