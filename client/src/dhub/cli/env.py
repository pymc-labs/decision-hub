"""Show the active dhub environment configuration."""

from rich.console import Console

from dhub.cli.config import config_file, get_api_url, get_env


def env_command() -> None:
    """Show the active environment, config file path, and API URL."""
    console = Console()
    env = get_env()
    console.print(f"Environment: {env}")
    console.print(f"Config: {config_file(env)}")
    console.print(f"API URL: {get_api_url()}")
