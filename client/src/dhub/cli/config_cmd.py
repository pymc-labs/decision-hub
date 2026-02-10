"""Configuration management commands."""

import typer
from rich.console import Console

console = Console()
config_app = typer.Typer(help="Manage CLI configuration", no_args_is_help=True)


@config_app.command("default-org")
def set_default_org_command() -> None:
    """Set the default namespace for publishing."""
    from dhub.cli.config import CliConfig, load_config, save_config

    config = load_config()

    if not config.orgs:
        console.print("[red]Error: No namespaces available. Run [bold]dhub login[/bold] to sync your orgs.[/]")
        raise typer.Exit(1)

    console.print("Available namespaces:")
    for i, org in enumerate(config.orgs, 1):
        marker = " [cyan](current default)[/]" if org == config.default_org else ""
        console.print(f"  {i}. {org}{marker}")

    choices: dict[str, str | None] = {str(i): org for i, org in enumerate(config.orgs, 1)}
    choices[str(len(config.orgs) + 1)] = None
    console.print(f"  {len(config.orgs) + 1}. (none)")

    selection = console.input("\nSelect a namespace by number: ").strip()

    if selection not in choices:
        console.print("[red]Invalid selection.[/]")
        raise typer.Exit(1)

    new_default = choices[selection]
    new_config = CliConfig(
        api_url=config.api_url,
        token=config.token,
        orgs=config.orgs,
        default_org=new_default,
    )
    save_config(new_config)

    if new_default:
        console.print(f"[green]Default namespace set to: {new_default}[/]")
    else:
        console.print("[green]Default namespace cleared.[/]")
