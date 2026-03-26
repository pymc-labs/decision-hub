"""Main Typer app with subcommand registration."""

import shutil
import subprocess
import sys
from importlib.metadata import version as pkg_version

import typer
from rich.console import Console


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
    output: str = typer.Option(
        "text",
        "--output",
        help="Output format: 'text' or 'json'.",
    ),
) -> None:
    """Decision Hub - The AI Skill Manager for Data Science Agents."""
    from dhub.cli.output import OutputFormat, set_format

    try:
        fmt = OutputFormat(output)
    except ValueError:
        raise typer.BadParameter(
            f"Invalid output format '{output}'. Must be 'text' or 'json'.",
            param_hint="'--output'",
        ) from None
    set_format(fmt)

    if output == "text":
        from dhub.cli.version_check import show_update_notice

        show_update_notice(Console(stderr=True))


# Register top-level commands
from dhub.cli.auth import login_command, logout_command  # noqa: E402
from dhub.cli.env import env_command  # noqa: E402
from dhub.cli.init import init_command  # noqa: E402
from dhub.cli.registry import (  # noqa: E402
    delete_command,
    eval_report_command,
    info_command,
    install_command,
    list_command,
    logs_command,
    publish_command,
    uninstall_command,
    update_command,
    visibility_command,
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
app.command("info")(info_command)
app.command("delete")(delete_command)
app.command("eval-report")(eval_report_command)
app.command("logs")(logs_command)
app.command("run")(run_command)
app.command("ask")(ask_command)
app.command("update")(update_command)
app.command("visibility")(visibility_command)

from dhub.cli.doctor import doctor_command  # noqa: E402

app.command("doctor")(doctor_command)


def _detect_installer() -> str:
    """Detect how dhub-cli was installed: 'uv', 'pipx', or 'pip'."""
    uv_bin = shutil.which("uv")
    if uv_bin:
        result = subprocess.run(
            [uv_bin, "tool", "list"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and any(line.startswith("dhub-cli") for line in result.stdout.splitlines()):
            return "uv"

    pipx_bin = shutil.which("pipx")
    if pipx_bin:
        result = subprocess.run(
            [pipx_bin, "list", "--short"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and any(line.startswith("dhub-cli") for line in result.stdout.splitlines()):
            return "pipx"

    return "pip"


def _require_bin(name: str) -> str:
    """Return the absolute path to *name*, or raise if not found."""
    path = shutil.which(name)
    if path is None:
        msg = f"'{name}' not found on PATH"
        raise FileNotFoundError(msg)
    return path


def _upgrade(installer: str, console: Console) -> int:
    """Run the upgrade command for the given installer and return exit code."""
    if installer == "uv":
        cmd = [_require_bin("uv"), "tool", "install", "dhub-cli", "--upgrade"]
    elif installer == "pipx":
        cmd = [_require_bin("pipx"), "upgrade", "dhub-cli"]
    else:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "dhub-cli"]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"[red]Upgrade failed:[/]\n{result.stderr.strip()}")
    return result.returncode


def _query_version(installer: str) -> str | None:
    """Query the installed dhub-cli version using the same tool that installed it."""
    if installer == "uv":
        result = subprocess.run(
            [_require_bin("uv"), "tool", "list"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("dhub-cli"):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1].lstrip("v")
        return None

    if installer == "pipx":
        result = subprocess.run(
            [_require_bin("pipx"), "list", "--short"],
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            if line.startswith("dhub-cli"):
                parts = line.split()
                if len(parts) >= 2:
                    return parts[1].lstrip("v")
        return None

    # pip — use the same Python that's running this process
    result = subprocess.run(
        [sys.executable, "-m", "pip", "show", "dhub-cli"],
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if line.startswith("Version:"):
            return line.split(":", 1)[1].strip()
    return None


def upgrade_command() -> None:
    """Upgrade dhub to the latest version from PyPI."""
    console = Console()
    current = pkg_version("dhub-cli")
    console.print(f"Current version: [bold]{current}[/]")

    installer = _detect_installer()
    console.print(f"Detected install method: [bold]{installer}[/]")
    console.print("Checking for updates...")

    if _upgrade(installer, console) != 0:
        raise typer.Exit(1)

    # Re-query the installed version after upgrade
    # (importlib cache is stale in the current process)
    new_version = _query_version(installer) or current

    if new_version == current:
        console.print(f"[green]Already up to date ({current}).[/]")
    else:
        console.print(f"[green]Upgraded: {current} → {new_version}[/]")


app.command("upgrade")(upgrade_command)

# Register subcommand groups
from dhub.cli.access import access_app  # noqa: E402
from dhub.cli.config_cmd import config_app  # noqa: E402
from dhub.cli.keys import keys_app  # noqa: E402
from dhub.cli.org import org_app  # noqa: E402

app.add_typer(access_app, name="access")
app.add_typer(org_app, name="org")
app.add_typer(keys_app, name="keys")
app.add_typer(config_app, name="config")


def run() -> None:
    """Entry point for the dhub CLI."""
    app()
