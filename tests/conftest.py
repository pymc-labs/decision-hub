"""Shared test fixtures for Decision Hub."""

from uuid import UUID

import pytest
from cryptography.fernet import Fernet

from decision_hub.models import User


@pytest.fixture
def jwt_secret() -> str:
    """A stable secret for signing JWTs in tests."""
    return "test-jwt-secret-that-is-long-enough"


@pytest.fixture
def fernet_key() -> str:
    """A real Fernet key for encryption round-trip tests."""
    return Fernet.generate_key().decode()


@pytest.fixture
def sample_user() -> User:
    """A frozen User dataclass for tests that need a realistic user."""
    return User(
        id=UUID("12345678-1234-5678-1234-567812345678"),
        github_id="gh-42",
        username="testuser",
    )
