"""Crash-safe checkpoint system for the GitHub skills crawler.

Persists discovery results and processing progress to a JSON file.
On resume, repos whose HEAD SHA hasn't changed are skipped.
Flushes every N results to balance durability vs. I/O at scale.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Checkpoint:
    """Tracks discovered and processed repos across crawler runs.

    ``processed_repos`` maps ``full_name`` → ``commit_sha`` so that
    re-runs can detect whether a repo has changed since last crawl.
    Legacy checkpoints that stored a plain list are auto-migrated on load.
    """

    discovered_repos: dict[str, dict] = field(default_factory=dict)
    processed_repos: dict[str, str | None] = field(default_factory=dict)
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
        """Load checkpoint from disk. Handles legacy list format."""
        data = json.loads(path.read_text())
        raw = data.get("processed_repos", {})
        # Migrate legacy list[str] → dict[str, None]
        if isinstance(raw, list):
            processed: dict[str, str | None] = {name: None for name in raw}
        else:
            processed = raw
        return cls(
            discovered_repos=data.get("discovered_repos", {}),
            processed_repos=processed,
        )

    def mark_processed(
        self,
        full_name: str,
        path: Path,
        commit_sha: str | None = None,
        flush_every: int = 100,
    ) -> None:
        """Record a processed repo with its commit SHA. Flush to disk every N results."""
        self.processed_repos[full_name] = commit_sha
        self._flush_counter += 1
        if self._flush_counter >= flush_every:
            self.save(path)
            self._flush_counter = 0

    def get_last_sha(self, full_name: str) -> str | None:
        """Return the stored commit SHA for a repo, or None if never processed."""
        return self.processed_repos.get(full_name)

    def flush(self, path: Path) -> None:
        """Force flush to disk (call after processing completes)."""
        if self._flush_counter > 0:
            self.save(path)
            self._flush_counter = 0
