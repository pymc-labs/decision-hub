"""Application settings loaded from environment variables."""

import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Decision Hub configuration. All values come from env vars or .env file."""

    model_config = {"extra": "ignore"}

    # Database
    database_url: str

    # S3 Storage
    s3_bucket: str
    aws_region: str = "us-east-1"
    aws_access_key_id: str
    aws_secret_access_key: str

    # GitHub OAuth
    github_client_id: str

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 8760  # 1 year

    # Encryption for API keys at rest
    fernet_key: str

    # Sprint 3: Modal
    modal_app_name: str = "decision-hub"

    # Sprint 4: Gemini Search
    google_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    # Access control: restrict login to members of a GitHub org.
    # Leave empty to allow all authenticated GitHub users.
    require_github_org: str = ""


def get_env() -> str:
    """Return current environment name from DHUB_ENV (default: 'prod')."""
    return os.environ.get("DHUB_ENV", "prod")


def create_settings(env: str | None = None) -> Settings:
    """Build Settings from the env-specific .env file (.env.dev, .env.prod).

    Environment variables still override values from the file.
    """
    env = env or get_env()
    return Settings(_env_file=f".env.{env}")
