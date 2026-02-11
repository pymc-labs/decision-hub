"""Crash-safe checkpoint system for the GitHub skills crawler.

Persists discovery results and processing progress to a JSON file.
On resume, already-processed repos are skipped. Flushes every N
results to balance durability vs. I/O at scale.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Checkpoint:
    """Tracks discovered and processed repos across crawler runs."""

    discovered_repos: dict[str, dict] = field(default_factory=dict)
    processed_repos: list[str] = field(default_factory=list)
    _flush_counter: int = field(default=0, repr=False)

    def save(self, path: Path) -> None:
        """Write checkpoint to disk."""
        data = {
            "discovered_repos": self.discovered_repos,
            "processed_repos": self.processed_repos,
        }
        path.write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: Path) -> "Checkpoint":
        """Load checkpoint from disk."""
        data = json.loads(path.read_text())
        return cls(
            discovered_repos=data.get("discovered_repos", {}),
            processed_repos=data.get("processed_repos", []),
        )

    def mark_processed(self, full_name: str, path: Path, flush_every: int = 100) -> None:
        """Append a processed repo. Flush to disk every N results."""
        self.processed_repos.append(full_name)
        self._flush_counter += 1
        if self._flush_counter >= flush_every:
            self.save(path)
            self._flush_counter = 0

    def flush(self, path: Path) -> None:
        """Force flush to disk (call after processing completes)."""
        if self._flush_counter > 0:
            self.save(path)
            self._flush_counter = 0
