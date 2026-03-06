"""Show the active dhub environment configuration."""

from rich.console import Console

from dhub.cli.config import config_file, get_api_url, get_env


def env_command() -> None:
    """Show the active environment, config file path, and API URL."""
    from dhub.cli.output import is_json, print_json

    env = get_env()
    cfg = str(config_file(env))
    api_url = get_api_url()

    if is_json():
        print_json({"environment": env, "config_file": cfg, "api_url": api_url})
        return

    console = Console()
    console.print(f"Environment: {env}")
    console.print(f"Config: {cfg}")
    console.print(f"API URL: {api_url}")
