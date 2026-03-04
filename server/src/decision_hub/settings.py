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
    s3_endpoint_url: str = ""  # Set to MinIO URL for local dev (e.g. http://localhost:9000)

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
    gemini_model: str = "gemini-3.1-flash-lite-preview"

    # Hybrid search settings
    search_candidate_limit: int = 20  # candidates per retrieval signal
    embedding_model: str = "gemini-embedding-001"

    # Authorization: comma-separated list of GitHub orgs.
    # When set, only members of these orgs can log in (checked at token
    # exchange time in auth_routes). Leave empty to allow all GitHub users.
    # NOTE: This is an *authorization* restriction, not authentication.
    # Authentication (valid JWT) is always required on write endpoints
    # regardless of this setting.
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

    # GitHub App credentials for tracker polling (mints installation tokens)
    github_app_id: str = ""
    github_app_private_key: str = ""
    github_app_installation_id: str = ""

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
    audit_log_rate_limit: int = 30  # max requests per window
    audit_log_rate_window: int = 60  # window in seconds

    # Sandbox resource limits for agent evals
    sandbox_memory_mb: int = 4096
    sandbox_timeout_seconds: int = 900
    sandbox_cpu: float = 2.0

    # Tracker batch size: max trackers claimed per loop iteration.
    # The cron loops until no more are due, so this controls lock granularity
    # rather than total throughput.
    tracker_batch_size: int = 1000
    # Jitter window (seconds) added to next_check_at to spread load
    tracker_jitter_seconds: int = 120
    # Stop processing if GitHub rate limit remaining drops below this
    tracker_rate_limit_floor: int = 500

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
