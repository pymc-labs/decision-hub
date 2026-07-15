"""CLI configuration file management for ~/.dhub/config.{env}.json."""

import contextlib
import json
import os
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path

import httpx

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

    Creates the ~/.dhub directory if it does not already exist. The
    config file contains a long-lived bearer token, so:

    - The directory is created with mode 0700 (owner-only) so a
      brand-new install is not readable by other local users.
    - The file is written atomically via a temp-then-``os.replace``
      dance: Ctrl-C mid-write no longer leaves the config half-written
      (which the loader treats as corrupted and asks the user to delete,
      losing their token).
    - The file itself is chmod'd to 0600 so an existing ~/.dhub with
      loose permissions is tightened on next save. On Windows this is a
      no-op because chmod semantics don't apply — POSIX users benefit,
      Windows behaviour is unchanged.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Tighten directory perms best-effort; ignore errors on Windows where
    # POSIX mode semantics don't apply.
    with contextlib.suppress(OSError, NotImplementedError):
        CONFIG_DIR.chmod(0o700)

    path = config_file()
    payload = json.dumps(asdict(config), indent=2) + "\n"

    # Write to a sibling temp file first so a mid-write interrupt cannot
    # leave the real config truncated. ``os.replace`` is atomic on POSIX
    # and Windows (Python 3.3+).
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    with contextlib.suppress(OSError, NotImplementedError):
        tmp.chmod(0o600)
    os.replace(tmp, path)


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
    env_token = os.environ.get("DHUB_TOKEN")
    if env_token:
        return env_token

    token = load_config().token
    if not token:
        from dhub.cli.output import ErrorCode, exit_error

        exit_error(ErrorCode.AUTH_REQUIRED, "Not logged in. Run 'dhub login' first.")
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


def raise_for_status(resp: httpx.Response) -> None:
    """Like ``resp.raise_for_status()`` but with a friendly 426 message.

    When the server returns 426 Upgrade Required, the raw httpx traceback
    exposes internal URLs and gives no guidance. This wrapper intercepts
    that status and prints an actionable message instead.
    """
    if resp.status_code == 426:
        from dhub.cli.output import ErrorCode, exit_error

        exit_error(
            ErrorCode.UPGRADE_REQUIRED,
            "Your dhub CLI is outdated and incompatible with the server. Run 'dhub upgrade'.",
            status=426,
            fatal=True,
        )
    resp.raise_for_status()
