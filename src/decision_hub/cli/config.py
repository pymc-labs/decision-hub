"""CLI configuration file management for ~/.dhub/config.json."""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import typer

CONFIG_DIR = Path.home() / ".dhub"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_API_URL = "https://decision-hub--api.modal.run"


@dataclass(frozen=True)
class CliConfig:
    """Immutable CLI configuration."""

    api_url: str = DEFAULT_API_URL
    token: str | None = None


def load_config() -> CliConfig:
    """Load CLI config from ~/.dhub/config.json.

    Returns defaults if the file does not exist or contains
    incomplete data.
    """
    if not CONFIG_FILE.exists():
        return CliConfig()

    raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return CliConfig(
        api_url=raw.get("api_url", DEFAULT_API_URL),
        token=raw.get("token"),
    )


def save_config(config: CliConfig) -> None:
    """Save CLI config to ~/.dhub/config.json.

    Creates the ~/.dhub directory if it does not already exist.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(asdict(config), indent=2) + "\n",
        encoding="utf-8",
    )


def get_api_url() -> str:
    """Get API URL from the DHUB_API_URL env var, falling back to saved config."""
    env_url = os.environ.get("DHUB_API_URL")
    if env_url:
        return env_url
    return load_config().api_url


def get_token() -> str:
    """Get the stored auth token.

    Raises:
        typer.Exit: If no token is stored (user not logged in).
    """
    from rich.console import Console

    token = load_config().token
    if not token:
        console = Console(stderr=True)
        console.print(
            "[red]Error: Not logged in. Run [bold]dhub login[/bold] first.[/]"
        )
        raise typer.Exit(1)
    return token
