"""Startup banner with 80s neon ASCII art and version update check."""

from __future__ import annotations

import logging

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

logger = logging.getLogger(__name__)

# Block-letter ASCII art — DECISION HUB on a single line.
_LOGO_LINES = (
    " ██████  ███████  ██████ ██ ███████ ██  ██████  ███    ██   ██   ██ ██    ██ ██████",
    " ██   ██ ██      ██      ██ ██      ██ ██    ██ ████   ██   ██   ██ ██    ██ ██   ██",
    " ██   ██ █████   ██      ██ ███████ ██ ██    ██ ██ ██  ██   ███████ ██    ██ ██████",
    " ██   ██ ██      ██      ██      ██ ██ ██    ██ ██  ██ ██   ██   ██ ██    ██ ██   ██",
    " ██████  ███████  ██████ ██ ███████ ██  ██████  ██   ████   ██   ██  ██████  ██████",
)

# 80s neon gradient stops: hot pink → magenta → purple → electric blue → cyan
_GRADIENT_STOPS: tuple[tuple[int, int, int], ...] = (
    (255, 16, 120),  # hot pink
    (255, 0, 210),  # magenta
    (180, 0, 255),  # purple
    (60, 80, 255),  # electric blue
    (0, 220, 255),  # cyan
)


def _lerp_color(c1: tuple[int, int, int], c2: tuple[int, int, int], t: float) -> str:
    """Linearly interpolate two RGB triples and return a hex color string."""
    r = int(c1[0] + (c2[0] - c1[0]) * t)
    g = int(c1[1] + (c2[1] - c1[1]) * t)
    b = int(c1[2] + (c2[2] - c1[2]) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _gradient_line(line: str) -> Text:
    """Apply a smooth horizontal neon gradient across a single line."""
    result = Text()
    n = len(line)
    if n == 0:
        return result
    stops = _GRADIENT_STOPS
    for i, ch in enumerate(line):
        if ch == " ":
            result.append(ch)
            continue
        t = i / max(n - 1, 1)
        pos = t * (len(stops) - 1)
        idx = min(int(pos), len(stops) - 2)
        frac = pos - idx
        color = _lerp_color(stops[idx], stops[idx + 1], frac)
        result.append(ch, style=f"bold {color}")
    return result


def print_banner(console: Console) -> None:
    """Print the neon Decision Hub logo."""
    console.print()
    for line in _LOGO_LINES:
        console.print(_gradient_line(line))
    console.print()


def _parse_semver(v: str) -> tuple[int, ...]:
    """Parse '1.2.3' into a comparable tuple."""
    return tuple(int(x) for x in v.split("."))


def check_and_show_update(console: Console) -> None:
    """Query the server for the latest CLI version and show an upgrade hint.

    Fails silently — an update check should never block the user.
    """
    try:
        import httpx

        from dhub.cli.config import build_headers, get_api_url, get_client_version

        current = get_client_version()
        api_url = get_api_url()

        with httpx.Client(timeout=5) as client:
            resp = client.get(
                f"{api_url}/cli/latest-version",
                headers=build_headers(),
            )
            if resp.status_code != 200:
                return
            data = resp.json()

        latest = data.get("latest_version", "")
        if not latest:
            return

        if _parse_semver(latest) > _parse_semver(current):
            console.print(
                Panel(
                    f"[bold]dhub update available![/bold] "
                    f"[dim]{current}[/dim] -> [bold cyan]{latest}[/bold cyan]\n"
                    f"Update with [bold]pip install --upgrade dhub-cli[/bold]",
                    border_style="cyan",
                )
            )
    except Exception:
        # Never let the update check crash the CLI
        logger.debug("Version check failed", exc_info=True)
