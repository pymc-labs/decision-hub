"""Main Typer app with subcommand registration."""

from importlib.metadata import version as pkg_version

import typer


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"dhub {pkg_version('dhub-cli')}")
        raise typer.Exit()


app = typer.Typer(
    name="dhub",
    no_args_is_help=True,
)


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Decision Hub - The AI Skill Manager for Data Science Agents."""


# Register top-level commands
from dhub.cli.auth import login_command, logout_command  # noqa: E402
from dhub.cli.env import env_command  # noqa: E402
from dhub.cli.init import init_command  # noqa: E402
from dhub.cli.registry import (  # noqa: E402
    delete_command,
    eval_report_command,
    install_command,
    list_command,
    logs_command,
    publish_command,
    uninstall_command,
)
from dhub.cli.runtime import run_command  # noqa: E402
from dhub.cli.search import ask_command  # noqa: E402

app.command("login")(login_command)
app.command("logout")(logout_command)
app.command("env")(env_command)
app.command("init")(init_command)
app.command("publish")(publish_command)
app.command("install")(install_command)
app.command("uninstall")(uninstall_command)
app.command("list")(list_command)
app.command("delete")(delete_command)
app.command("eval-report")(eval_report_command)
app.command("logs")(logs_command)
app.command("run")(run_command)
app.command("ask")(ask_command)

# Register subcommand groups
from dhub.cli.config_cmd import config_app  # noqa: E402
from dhub.cli.keys import keys_app  # noqa: E402
from dhub.cli.org import org_app  # noqa: E402
from dhub.cli.track import track_app  # noqa: E402

app.add_typer(org_app, name="org")
app.add_typer(keys_app, name="keys")
app.add_typer(config_app, name="config")
app.add_typer(track_app, name="track")


def run() -> None:
    """Entry point for the dhub CLI."""
    app()
