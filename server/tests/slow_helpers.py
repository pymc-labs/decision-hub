"""Shared helpers for slow (LLM-hitting) integration tests.

Provides API key loading, default model resolution, and latency tracking
used across gauntlet, ask, and topicality guard test suites.
"""

from __future__ import annotations

import os
import statistics
import time
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path


def load_google_api_key() -> str | None:
    """Load GOOGLE_API_KEY from environment or server/.env files.

    Checks (in order): environment variable, .env.dev, .env.prod.
    Returns the key string, or None if unavailable.
    """
    key = os.environ.get("GOOGLE_API_KEY", "")
    if key:
        return key

    server_dir = Path(__file__).resolve().parents[1]
    for env_file in (".env.dev", ".env.prod"):
        path = server_dir / env_file
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line.startswith("GOOGLE_API_KEY="):
                    val = line.split("=", 1)[1].strip().strip("\"'")
                    if val:
                        return val
    return None


def get_default_gemini_model() -> str:
    """Return the default Gemini model from Settings without loading env vars.

    Reads the Pydantic field default directly, avoiding any side effects
    from instantiating Settings (which requires DB URLs, etc.).
    """
    from decision_hub.settings import Settings

    return Settings.model_fields["gemini_model"].default


@dataclass
class LatencyTracker:
    """Collects wall-clock timings and prints p50/p95 summary.

    Emits a warning (visible in pytest output) if p95 exceeds soft_p95_limit.
    """

    label: str
    soft_p95_limit: float = 15.0
    _durations: list[float] = field(default_factory=list)

    def record(self, duration: float) -> None:
        self._durations.append(duration)

    def summary(self) -> str:
        if not self._durations:
            return f"[{self.label}] No timings recorded"

        n = len(self._durations)
        p50 = statistics.median(self._durations)
        # For p95, use the 95th percentile; fall back to max for small samples
        if n >= 20:
            sorted_d = sorted(self._durations)
            p95_idx = int(n * 0.95)
            p95 = sorted_d[min(p95_idx, n - 1)]
        else:
            p95 = max(self._durations)

        total = sum(self._durations)
        text = f"[{self.label}] n={n}, total={total:.1f}s, p50={p50:.2f}s, p95={p95:.2f}s"

        if p95 > self.soft_p95_limit:
            warnings.warn(
                f"{self.label} p95 latency ({p95:.2f}s) exceeds soft limit ({self.soft_p95_limit}s)",
                stacklevel=2,
            )
        return text


@contextmanager
def timed(tracker: LatencyTracker):
    """Context manager that records wall-clock duration to a LatencyTracker."""
    start = time.monotonic()
    yield
    tracker.record(time.monotonic() - start)
