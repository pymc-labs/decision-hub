"""CLI configuration file management for ~/.dhub/config.{env}.json."""

import json
import os
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path

import typer

CONFIG_DIR = Path.home() / ".dhub"

# Per-environment default API URLs
_DEFAULT_API_URLS: dict[str, str] = {
    "dev": "https://pymc-labs--api-dev.modal.run",
    "prod": "https://pymc-labs--api.modal.run",
}


def get_env() -> str:
    """Return current environment name from DHUB_ENV (default: 'prod')."""
    return os.environ.get("DHUB_ENV", "prod")


def default_api_url(env: str | None = None) -> str:
    """Return the default API URL for the given environment."""
    env = env or get_env()
    return _DEFAULT_API_URLS.get(env, _DEFAULT_API_URLS["prod"])


def config_file(env: str | None = None) -> Path:
    """Return the config file path for the given environment."""
    env = env or get_env()
    return CONFIG_DIR / f"config.{env}.json"


@dataclass(frozen=True)
class CliConfig:
    """Immutable CLI configuration."""

    api_url: str = ""
    token: str | None = None
    orgs: tuple[str, ...] = ()
    default_org: str | None = None


def load_config() -> CliConfig:
    """Load CLI config from ~/.dhub/config.{env}.json.

    Falls back to the legacy ~/.dhub/config.json if the env-specific
    file does not exist yet (smooth migration for existing users).
    Returns defaults if neither file exists.
    """
    env = get_env()
    path = config_file(env)
    # Migration: fall back to legacy config.json for existing prod users
    if not path.exists():
        legacy_path = CONFIG_DIR / "config.json"
        if env == "prod" and legacy_path.exists():
            path = legacy_path
        else:
            return CliConfig(api_url=default_api_url(env))

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        import typer
        from rich.console import Console

        Console(stderr=True).print(
            f"[red]Error: Config file is corrupted: {path}\nDelete it and run [bold]dhub login[/bold] again.[/]"
        )
        raise typer.Exit(1) from None
    return CliConfig(
        api_url=raw.get("api_url", default_api_url()),
        token=raw.get("token"),
        orgs=tuple(raw.get("orgs", ())),
        default_org=raw.get("default_org"),
    )


def save_config(config: CliConfig) -> None:
    """Save CLI config to ~/.dhub/config.{env}.json.

    Creates the ~/.dhub directory if it does not already exist.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = config_file()
    path.write_text(
        json.dumps(asdict(config), indent=2) + "\n",
        encoding="utf-8",
    )


def get_api_url() -> str:
    """Get API URL from the DHUB_API_URL env var, falling back to saved config."""
    env_url = os.environ.get("DHUB_API_URL")
    if env_url:
        return env_url.rstrip("/")
    return load_config().api_url.rstrip("/")


def get_token() -> str:
    """Get the auth token from DHUB_TOKEN env var or saved config.

    Raises:
        typer.Exit: If no token is available (user not logged in).
    """
    from rich.console import Console

    env_token = os.environ.get("DHUB_TOKEN")
    if env_token:
        return env_token

    token = load_config().token
    if not token:
        console = Console(stderr=True)
        console.print("[red]Error: Not logged in. Run [bold]dhub login[/bold] first.[/]")
        raise typer.Exit(1)
    return token


def get_optional_token() -> str | None:
    """Get the auth token if available, or ``None`` if not logged in.

    Unlike :func:`get_token`, this never exits — it simply returns
    ``None`` when no credentials are configured.  Use this for commands
    that work without authentication (e.g. installing public skills).
    """
    env_token = os.environ.get("DHUB_TOKEN")
    if env_token:
        return env_token
    return load_config().token


def get_default_org() -> str | None:
    """Get the default org from DHUB_DEFAULT_ORG env var or saved config."""
    env_org = os.environ.get("DHUB_DEFAULT_ORG")
    if env_org:
        return env_org
    return load_config().default_org


def get_client_version() -> str:
    """Return the installed dhub-cli package version."""
    return version("dhub-cli")


def build_headers(token: str | None = None) -> dict[str, str]:
    """Build HTTP headers with the CLI version and optional auth token.

    Every request to the server includes X-DHub-Client-Version so the
    server can enforce a minimum CLI version. Authenticated requests
    also include the Authorization bearer header.
    """
    headers: dict[str, str] = {"X-DHub-Client-Version": get_client_version()}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers
