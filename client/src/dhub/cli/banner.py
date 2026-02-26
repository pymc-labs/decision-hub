"""Startup banner with 80s neon ASCII art and version update check."""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

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


def check_and_show_update(console: Console) -> None:
    """Show an upgrade hint if a newer version is available on PyPI.

    Delegates to :mod:`dhub.cli.version_check` which caches results for
    24 hours.  Fails silently — an update check should never block the user.
    """
    from dhub.cli.version_check import show_update_notice

    show_update_notice(console)
