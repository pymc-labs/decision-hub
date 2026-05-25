"""CLI configuration file management for ~/.dhub/config.{env}.json."""

import contextlib
import json
import os
import stat
import tempfile
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path

import httpx

CONFIG_DIR = Path.home() / ".dhub"

# Owner read+write only — protects the auth token from other users on
# shared machines. Default umask is typically 0o022 which would leave
# the file world-readable.
_CONFIG_FILE_MODE = 0o600
_CONFIG_DIR_MODE = 0o700

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

    Writes are atomic and the resulting file is owner-read/write only
    (mode 0o600). The atomic part matters because ``load_config()``
    will refuse to read a truncated JSON file and force the user to
    re-authenticate, and we'd rather not corrupt the file at all if
    the process is killed mid-write. The permission part matters
    because the file contains a long-lived bearer token; the default
    umask of 0o022 would leave it world-readable on most systems.

    Implementation: write to a sibling tempfile in ``~/.dhub`` (same
    filesystem so ``rename`` is atomic), ``chmod`` to 0o600 *before*
    rename (so there's never a window where the live config has loose
    permissions), then ``os.replace`` to swap it in. The replace is
    POSIX-atomic and also overwrites on Windows.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Tighten directory perms too — best-effort; ignore errors so we
    # don't fail on filesystems that don't honour chmod (e.g. some
    # network mounts).
    with contextlib.suppress(OSError):
        CONFIG_DIR.chmod(_CONFIG_DIR_MODE)

    path = config_file()
    payload = json.dumps(asdict(config), indent=2) + "\n"

    # mkstemp gives us a securely-created file (mode 0o600 on POSIX by
    # default) in the target directory, so the os.replace below stays
    # on a single filesystem and is atomic.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(CONFIG_DIR),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        # Belt-and-braces: explicit chmod in case the platform's
        # mkstemp default differs (it shouldn't on POSIX, but Windows
        # ACLs work differently).
        with contextlib.suppress(OSError):
            os.chmod(tmp_path, _CONFIG_FILE_MODE)
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort cleanup of the tempfile if anything went wrong
        # before the rename — the original file is untouched.
        with contextlib.suppress(OSError):
            tmp_path.unlink()
        raise

    # Re-assert perms on the destination — covers the case where the
    # file already existed with looser permissions; on POSIX,
    # ``os.replace`` keeps the *new* inode's perms, but being explicit
    # protects against platform quirks.
    with contextlib.suppress(OSError):
        os.chmod(path, _CONFIG_FILE_MODE)


def is_config_file_secure(path: Path | None = None) -> bool:
    """Return True if the config file's POSIX perms restrict it to the owner.

    Used by ``dhub doctor`` and by tests. On non-POSIX systems where the
    permission bits don't map cleanly (e.g. Windows), returns True — we
    rely on filesystem ACLs there and don't second-guess them.
    """
    path = path or config_file()
    if not path.exists():
        return True
    try:
        mode = path.stat().st_mode
    except OSError:
        return True
    # Any group or other perm set is considered insecure.
    return (mode & (stat.S_IRWXG | stat.S_IRWXO)) == 0


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
