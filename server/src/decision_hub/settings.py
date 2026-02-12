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

    # Hybrid search settings
    search_candidate_limit: int = 20  # candidates per retrieval signal
    embedding_model: str = "gemini-embedding-001"

    # Access control: comma-separated list of GitHub orgs.
    # User must belong to at least one. Leave empty to allow all.
    require_github_org: str = ""

    @property
    def required_github_orgs(self) -> list[str]:
        """Parse comma-separated org list into individual org slugs."""
        if not self.require_github_org:
            return []
        return [o.strip() for o in self.require_github_org.split(",") if o.strip()]

    # Minimum CLI version allowed to call /v1/ endpoints.
    # Empty string disables enforcement (backward-compatible rollout).
    min_cli_version: str = ""

    # Latest published CLI version. Served via /cli/latest-version so the
    # CLI can suggest upgrades. Empty string disables the check.
    latest_cli_version: str = ""

    # GitHub token for tracker API calls (private repos / rate limits)
    github_token: str = ""

    # Rate limiting (per IP, sliding window)
    search_rate_limit: int = 20  # max requests per window
    search_rate_window: int = 60  # window in seconds

    # Public endpoint rate limits
    list_skills_rate_limit: int = 120  # max requests per window
    list_skills_rate_window: int = 60  # window in seconds
    resolve_rate_limit: int = 60  # max requests per window
    resolve_rate_window: int = 60  # window in seconds
    download_rate_limit: int = 20  # max requests per window
    download_rate_window: int = 60  # window in seconds

    # Logging level (DEBUG, INFO, WARNING, ERROR). Default: INFO.
    log_level: str = "INFO"


def get_env() -> str:
    """Return current environment name from DHUB_ENV (default: 'dev')."""
    return os.environ.get("DHUB_ENV", "dev")


def create_settings(env: str | None = None) -> Settings:
    """Build Settings from the env-specific .env file (.env.dev, .env.prod).

    Environment variables still override values from the file.
    """
    env = env or get_env()
    return Settings(_env_file=f".env.{env}")
