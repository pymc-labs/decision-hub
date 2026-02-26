"""Startup version check against PyPI with local caching.

Queries PyPI once per day for the latest dhub-cli version and shows a
Rich panel when an update is available.  The check is designed to never
block or slow down normal CLI usage:

* 3-second HTTP timeout
* 24-hour local cache in ``~/.dhub/.version_cache.json``
* All exceptions caught silently
* Opt-out via ``DHUB_NO_UPDATE_CHECK=1``
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

logger = logging.getLogger(__name__)

_PYPI_URL = "https://pypi.org/pypi/dhub-cli/json"
_CACHE_TTL_SECONDS = 86_400  # 24 hours


def _cache_path() -> Path:
    from dhub.cli.config import CONFIG_DIR

    return CONFIG_DIR / ".version_cache.json"


def _parse_semver(v: str) -> tuple[int, ...]:
    """Parse '1.2.3' into a comparable tuple."""
    return tuple(int(x) for x in v.split("."))


def _read_cache() -> str | None:
    """Return the cached latest version if the cache is still fresh."""
    try:
        path = _cache_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        checked_at = data.get("checked_at", 0)
        if time.time() - checked_at > _CACHE_TTL_SECONDS:
            return None
        return data.get("latest_version")
    except Exception:
        return None


def _write_cache(latest_version: str) -> None:
    """Persist the latest version and current timestamp to disk."""
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"latest_version": latest_version, "checked_at": time.time()}) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def _fetch_latest_from_pypi() -> str | None:
    """Fetch the latest version string from PyPI (3s timeout)."""
    import httpx

    with httpx.Client(timeout=3) as client:
        resp = client.get(_PYPI_URL)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("info", {}).get("version")


def get_latest_version() -> str | None:
    """Return the latest PyPI version, using cache when available."""
    cached = _read_cache()
    if cached is not None:
        return cached

    latest = _fetch_latest_from_pypi()
    if latest:
        _write_cache(latest)
    return latest


def show_update_notice(console: Console) -> None:
    """Show a Rich panel if a newer version of dhub-cli is available.

    Respects ``DHUB_NO_UPDATE_CHECK=1`` to opt out.  Fails silently on
    any error so it never disrupts the user's workflow.
    """
    try:
        if os.environ.get("DHUB_NO_UPDATE_CHECK", "").strip() == "1":
            return

        from dhub.cli.config import get_client_version

        current = get_client_version()
        latest = get_latest_version()
        if not latest:
            return

        if _parse_semver(latest) > _parse_semver(current):
            console.print(
                Panel(
                    f"[bold]dhub update available![/bold]  "
                    f"[dim]{current}[/dim] → [bold cyan]{latest}[/bold cyan]\n"
                    f"Run [bold]dhub upgrade[/bold] to update",
                    border_style="cyan",
                )
            )
    except Exception:
        logger.debug("Version check failed", exc_info=True)
