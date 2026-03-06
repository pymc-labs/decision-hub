import json
from pathlib import Path

import pytest

from dhub_core.plugin_manifest import (
    detect_plugin_platforms,
    parse_plugin_manifest,
)


@pytest.fixture
def plugin_repo(tmp_path: Path) -> Path:
    """Create a minimal plugin directory structure."""
    # .claude-plugin/plugin.json
    claude_dir = tmp_path / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "test-plugin",
                "description": "A test plugin",
                "version": "1.0.0",
                "author": {"name": "Test Author", "email": "test@example.com"},
                "homepage": "https://example.com",
                "repository": "https://github.com/test/test-plugin",
                "license": "MIT",
                "keywords": ["test", "example"],
            }
        )
    )

    # .cursor-plugin/plugin.json (second platform)
    cursor_dir = tmp_path / ".cursor-plugin"
    cursor_dir.mkdir()
    (cursor_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "test-plugin",
                "description": "A test plugin for Cursor",
                "version": "1.0.0",
            }
        )
    )

    # skills/my-skill/SKILL.md
    skills_dir = tmp_path / "skills" / "my-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: A test skill\n---\nBody text")

    # hooks/hooks.json
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    (hooks_dir / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup",
                            "hooks": [{"type": "command", "command": "echo hello", "async": False}],
                        }
                    ],
                }
            }
        )
    )

    # agents/code-reviewer.md
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "code-reviewer.md").write_text("# Code Reviewer Agent")

    # commands/build.md
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir()
    (commands_dir / "build.md").write_text("# Build command")

    return tmp_path


def test_detect_plugin_platforms(plugin_repo: Path):
    platforms = detect_plugin_platforms(plugin_repo)
    assert platforms == ["claude", "cursor"]


def test_detect_plugin_platforms_empty(tmp_path: Path):
    platforms = detect_plugin_platforms(tmp_path)
    assert platforms == []


def test_detect_plugin_platforms_no_plugin_json(tmp_path: Path):
    (tmp_path / ".claude-plugin").mkdir()
    # No plugin.json inside
    platforms = detect_plugin_platforms(tmp_path)
    assert platforms == []


def test_parse_plugin_manifest(plugin_repo: Path):
    manifest = parse_plugin_manifest(plugin_repo)
    assert manifest.name == "test-plugin"
    assert manifest.description == "A test plugin"
    assert manifest.version == "1.0.0"
    assert manifest.author_name == "Test Author"
    assert manifest.author_email == "test@example.com"
    assert manifest.homepage == "https://example.com"
    assert manifest.license == "MIT"
    assert manifest.platforms == ("claude", "cursor")
    assert len(manifest.skills) == 1
    assert manifest.skills[0].name == "my-skill"
    assert len(manifest.hooks) == 1
    assert manifest.hooks[0].event == "SessionStart"
    assert manifest.hooks[0].command == "echo hello"
    assert len(manifest.agents) == 1
    assert manifest.agents[0] == "code-reviewer"
    assert len(manifest.commands) == 1
    assert manifest.commands[0] == "build"


def test_parse_plugin_manifest_minimal(tmp_path: Path):
    claude_dir = tmp_path / ".claude-plugin"
    claude_dir.mkdir()
    (claude_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "minimal",
                "description": "Minimal plugin",
                "version": "0.1.0",
            }
        )
    )
    manifest = parse_plugin_manifest(tmp_path)
    assert manifest.name == "minimal"
    assert manifest.platforms == ("claude",)
    assert manifest.skills == ()
    assert manifest.hooks == ()
    assert manifest.agents == ()
    assert manifest.commands == ()


def test_parse_plugin_manifest_no_plugin_dirs(tmp_path: Path):
    with pytest.raises(ValueError, match="No plugin platform directories found"):
        parse_plugin_manifest(tmp_path)


def test_parse_plugin_manifest_missing_name(tmp_path: Path) -> None:
    """plugin.json without 'name' raises ValueError, not KeyError."""
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text('{"description": "no name"}')
    with pytest.raises(ValueError, match="missing required 'name'"):
        parse_plugin_manifest(tmp_path)


def test_parse_plugin_manifest_invalid_json(tmp_path: Path) -> None:
    """Malformed JSON in plugin.json raises json.JSONDecodeError."""
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text("{not valid json")
    with pytest.raises(json.JSONDecodeError):
        parse_plugin_manifest(tmp_path)


def test_discover_hooks_malformed_json(tmp_path: Path) -> None:
    """Malformed hooks.json is skipped, not crashed on."""
    plugin_dir = tmp_path / ".claude-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text('{"name": "test", "description": "t"}')
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    (hooks_dir / "hooks.json").write_text("{broken")

    manifest = parse_plugin_manifest(tmp_path)
    assert manifest.hooks == ()
