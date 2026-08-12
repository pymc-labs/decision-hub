"""Tests for decision_hub.scripts.crawler.checkpoint -- atomic checkpoint save."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from decision_hub.scripts.crawler.checkpoint import Checkpoint


def test_save_writes_via_tmp_and_replace(tmp_path: Path) -> None:
    """Checkpoint.save writes to <path>.tmp then os.replaces it into place.

    Regression: previously a SIGKILL/OOM between write_text() and its
    fsync could leave a truncated JSON file that failed the next load(),
    losing the entire crawl state even though the docstring called it
    "crash-safe".
    """
    checkpoint_path = tmp_path / "checkpoint.json"
    tmp_target = tmp_path / "checkpoint.json.tmp"

    cp = Checkpoint(processed_repos={"acme/widget": "sha1"})

    original_replace = __import__("os").replace
    captured: dict[str, bool] = {}

    def replace_spy(src: str, dst: str) -> None:
        # By the time we hit os.replace the tmp file must already contain
        # the full JSON payload — a crash before this line must leave the
        # real checkpoint intact.
        captured["tmp_exists"] = Path(src).is_file()
        captured["tmp_content"] = Path(src).read_text()
        original_replace(src, dst)

    with patch("decision_hub.scripts.crawler.checkpoint.os.replace", side_effect=replace_spy):
        cp.save(checkpoint_path)

    assert captured["tmp_exists"] is True
    assert json.loads(captured["tmp_content"]) == {
        "discovered_repos": {},
        "processed_repos": {"acme/widget": "sha1"},
    }
    # After a successful save the tmp file has been renamed away.
    assert not tmp_target.exists()
    assert checkpoint_path.exists()


def test_save_leaves_previous_checkpoint_intact_on_crash(tmp_path: Path) -> None:
    """If the process is killed mid-save, the original file must survive."""
    checkpoint_path = tmp_path / "checkpoint.json"
    # Seed a valid prior checkpoint
    prior = Checkpoint(processed_repos={"acme/widget": "sha_prior"})
    prior.save(checkpoint_path)
    original_content = checkpoint_path.read_text()

    # Simulate a crash during os.replace — the tmp file was written but
    # never renamed. The original checkpoint must remain untouched.
    fresh = Checkpoint(processed_repos={"acme/widget": "sha_new"})
    with (
        patch(
            "decision_hub.scripts.crawler.checkpoint.os.replace",
            side_effect=OSError("simulated SIGKILL"),
        ),
        pytest.raises(OSError, match="simulated SIGKILL"),
    ):
        fresh.save(checkpoint_path)

    assert checkpoint_path.read_text() == original_content
    # The load path must still work — no corruption.
    loaded = Checkpoint.load(checkpoint_path)
    assert loaded.processed_repos == {"acme/widget": "sha_prior"}
