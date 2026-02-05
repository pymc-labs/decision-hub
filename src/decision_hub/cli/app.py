"""Main Typer app with subcommand registration."""

import typer

app = typer.Typer(
    name="dhub",
    help="Decision Hub - The package manager for AI agent skills",
    no_args_is_help=True,
)

# Register top-level commands
from decision_hub.cli.auth import login_command  # noqa: E402
from decision_hub.cli.registry import install_command, publish_command  # noqa: E402
from decision_hub.cli.runtime import run_command  # noqa: E402
from decision_hub.cli.search import ask_command  # noqa: E402

app.command("login")(login_command)
app.command("publish")(publish_command)
app.command("install")(install_command)
app.command("run")(run_command)
app.command("ask")(ask_command)

# Register subcommand groups
from decision_hub.cli.keys import keys_app  # noqa: E402
from decision_hub.cli.org import org_app  # noqa: E402

app.add_typer(org_app, name="org")
app.add_typer(keys_app, name="keys")


def run() -> None:
    """Entry point for the dhub CLI."""
    app()
