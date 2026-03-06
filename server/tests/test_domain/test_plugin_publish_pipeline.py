"""Tests for plugin publish pipeline."""

import io
import json
import zipfile
from pathlib import Path

import pytest

from decision_hub.domain.plugin_publish_pipeline import (
    PluginPublishResult,
    extract_plugin_for_evaluation,
    extract_plugin_to_dir,
)


def _build_plugin_zip(*, hooks: list | None = None) -> bytes:
    """Build a minimal plugin zip for testing."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            ".claude-plugin/plugin.json",
            json.dumps(
                {
                    "name": "test-plugin",
                    "description": "A test plugin",
                    "version": "1.0.0",
                }
            ),
        )
        zf.writestr(
            "skills/my-skill/SKILL.md",
            "---\nname: my-skill\ndescription: A test skill\n---\nBody",
        )
        if hooks:
            hooks_data = {"hooks": {"SessionStart": [{"matcher": "startup", "hooks": hooks}]}}
            zf.writestr("hooks/hooks.json", json.dumps(hooks_data))
        zf.writestr("main.py", "print('hello')")
    return buf.getvalue()


def test_extract_plugin_for_evaluation():
    """Extract plugin zip returns scannable files."""
    zip_bytes = _build_plugin_zip()
    source_files, _unscanned = extract_plugin_for_evaluation(zip_bytes)
    filenames = [f for f, _ in source_files]
    assert ".claude-plugin/plugin.json" in filenames
    assert "main.py" in filenames


def test_extract_plugin_for_evaluation_with_hooks():
    """Extract plugin zip includes hooks.json when present."""
    zip_bytes = _build_plugin_zip(hooks=[{"command": "echo hi"}])
    source_files, _unscanned = extract_plugin_for_evaluation(zip_bytes)
    filenames = [f for f, _ in source_files]
    assert "hooks/hooks.json" in filenames


def test_extract_plugin_to_dir(tmp_path: Path):
    """Extract plugin zip to directory for manifest parsing."""
    zip_bytes = _build_plugin_zip()
    extract_plugin_to_dir(zip_bytes, str(tmp_path))
    assert (tmp_path / ".claude-plugin" / "plugin.json").exists()
    assert (tmp_path / "skills" / "my-skill" / "SKILL.md").exists()


def test_extract_plugin_for_evaluation_unscannable():
    """Binary files are tracked as unscanned."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            ".claude-plugin/plugin.json",
            json.dumps({"name": "p", "description": "d", "version": "1.0.0"}),
        )
        zf.writestr("image.png", b"\x89PNG\r\n")
    zip_bytes = buf.getvalue()

    source_files, unscanned = extract_plugin_for_evaluation(zip_bytes)
    assert "image.png" in unscanned
    filenames = [f for f, _ in source_files]
    assert "image.png" not in filenames


def test_extract_plugin_too_many_entries():
    """Zip with too many entries raises ValueError."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            ".claude-plugin/plugin.json",
            json.dumps({"name": "p", "description": "d", "version": "1.0.0"}),
        )
        for i in range(501):
            zf.writestr(f"file_{i}.txt", "x")
    zip_bytes = buf.getvalue()

    with pytest.raises(ValueError, match="exceeding limit"):
        extract_plugin_for_evaluation(zip_bytes)


def test_plugin_publish_result_is_frozen():
    """PluginPublishResult is immutable."""
    from uuid import uuid4

    result = PluginPublishResult(
        plugin_id=uuid4(),
        version_id=uuid4(),
        version="1.0.0",
        s3_key="plugins/org/name/1.0.0.zip",
        checksum="abc123",
        eval_status="A",
        deprecated_skills_count=0,
    )
    with pytest.raises(AttributeError):
        result.version = "2.0.0"  # type: ignore[misc]
