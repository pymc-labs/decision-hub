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

    Creates the ~/.dhub directory if it does not already exist.

    The token is a bearer credential, so we write the file 0600 (owner
    read/write only) via a temp-file + atomic rename. The rename also
    protects against a partially-written file if the process is killed
    mid-write -- ``load_config`` would otherwise treat the JSON as
    "corrupted" and force the user to re-login.

    On Windows, ``os.chmod``/POSIX permission bits are a no-op; anyone
    protecting a home directory there should already be relying on OS
    ACLs rather than umask.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Restrict the parent dir too so a subsequent user on a shared host
    # can't at least list the config file names.
    with contextlib.suppress(OSError):
        os.chmod(CONFIG_DIR, 0o700)

    path = config_file()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(asdict(config), indent=2) + "\n"
    # Open with restrictive mode so the token bytes never touch disk with
    # default umask (typically 0644 -> world-readable on shared hosts).
    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
    except Exception:
        # Best-effort cleanup so a failed write doesn't leave a rogue
        # .tmp file next to the real config.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise
    os.replace(tmp_path, path)


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
