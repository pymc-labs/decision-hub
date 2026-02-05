"""Tests for SKILL.md parsing and validation."""

from pathlib import Path

import pytest

from decision_hub.domain.skill_manifest import (
    parse_skill_md,
    validate_manifest,
)
from decision_hub.models import RuntimeConfig, SkillManifest, TestingConfig


VALID_SKILL_MD = """\
---
name: test-skill
description: A test skill for unit testing.
runtime:
  driver: "local/uv"
  entrypoint: "src/main.py"
  lockfile: "uv.lock"
  env: ["OPENAI_API_KEY"]
testing:
  cases: "tests/cases.json"
  agents:
    - name: "claude"
      required_keys: ["ANTHROPIC_API_KEY"]
---
You are a test assistant.
"""

MINIMAL_SKILL_MD = """\
---
name: minimal-skill
description: A minimal skill with no optional fields.
---
You are a minimal assistant.
"""

SKILL_MD_WITH_ALL_OPTIONAL = """\
---
name: full-skill
description: A skill with all optional fields.
license: MIT
compatibility: ">=0.1.0"
metadata:
  author: testauthor
  category: testing
allowed_tools: "Read,Write,Bash"
runtime:
  driver: "local/uv"
  entrypoint: "main.py"
  lockfile: "uv.lock"
  env: []
---
You are a fully-configured assistant.
"""


def _write_skill_md(tmp_path: Path, content: str) -> Path:
    """Write content to a SKILL.md file in a temp directory and return the path."""
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(content)
    return skill_md


class TestParseSkillMd:
    """Tests for parse_skill_md function."""

    def test_parse_valid_skill_md(self, tmp_path: Path) -> None:
        path = _write_skill_md(tmp_path, VALID_SKILL_MD)
        manifest = parse_skill_md(path)

        assert manifest.name == "test-skill"
        assert manifest.description == "A test skill for unit testing."
        assert manifest.body == "You are a test assistant."
        assert manifest.runtime is not None
        assert manifest.runtime.driver == "local/uv"
        assert manifest.runtime.entrypoint == "src/main.py"
        assert manifest.runtime.lockfile == "uv.lock"
        assert manifest.runtime.env == ("OPENAI_API_KEY",)
        assert manifest.testing is not None
        assert manifest.testing.cases == "tests/cases.json"
        assert len(manifest.testing.agents) == 1
        assert manifest.testing.agents[0].name == "claude"
        assert manifest.testing.agents[0].required_keys == ("ANTHROPIC_API_KEY",)

    def test_parse_minimal_skill_md(self, tmp_path: Path) -> None:
        path = _write_skill_md(tmp_path, MINIMAL_SKILL_MD)
        manifest = parse_skill_md(path)

        assert manifest.name == "minimal-skill"
        assert manifest.description == "A minimal skill with no optional fields."
        assert manifest.body == "You are a minimal assistant."
        assert manifest.runtime is None
        assert manifest.testing is None
        assert manifest.license is None
        assert manifest.compatibility is None
        assert manifest.metadata is None
        assert manifest.allowed_tools is None

    def test_parse_all_optional_fields(self, tmp_path: Path) -> None:
        path = _write_skill_md(tmp_path, SKILL_MD_WITH_ALL_OPTIONAL)
        manifest = parse_skill_md(path)

        assert manifest.name == "full-skill"
        assert manifest.license == "MIT"
        assert manifest.compatibility == ">=0.1.0"
        assert manifest.metadata == {"author": "testauthor", "category": "testing"}
        assert manifest.allowed_tools == "Read,Write,Bash"
        assert manifest.runtime is not None
        assert manifest.runtime.env == ()

    def test_missing_name_raises(self, tmp_path: Path) -> None:
        content = """\
---
description: No name field.
---
Body text.
"""
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="name"):
            parse_skill_md(path)

    def test_missing_description_raises(self, tmp_path: Path) -> None:
        content = """\
---
name: no-desc
---
Body text.
"""
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="description"):
            parse_skill_md(path)

    def test_invalid_name_uppercase_raises(self, tmp_path: Path) -> None:
        content = """\
---
name: InvalidName
description: Has uppercase name.
---
Body text.
"""
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="Invalid name"):
            parse_skill_md(path)

    def test_invalid_name_starts_with_hyphen_raises(self, tmp_path: Path) -> None:
        content = """\
---
name: -starts-with-hyphen
description: Starts with hyphen.
---
Body text.
"""
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="Invalid name"):
            parse_skill_md(path)

    def test_name_too_long_raises(self, tmp_path: Path) -> None:
        long_name = "a" * 65
        content = f"""\
---
name: {long_name}
description: Name is too long.
---
Body text.
"""
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="Invalid name"):
            parse_skill_md(path)

    def test_description_too_long_raises(self, tmp_path: Path) -> None:
        long_desc = "x" * 1025
        content = f"""\
---
name: valid-name
description: "{long_desc}"
---
Body text.
"""
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="[Dd]escription"):
            parse_skill_md(path)

    def test_missing_frontmatter_delimiters_raises(self, tmp_path: Path) -> None:
        content = "Just a body with no frontmatter."
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="---"):
            parse_skill_md(path)

    def test_missing_closing_delimiter_raises(self, tmp_path: Path) -> None:
        content = """\
---
name: test
description: Missing closing delimiter.
"""
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="closing"):
            parse_skill_md(path)

    def test_empty_body_raises(self, tmp_path: Path) -> None:
        content = """\
---
name: empty-body
description: Has an empty body.
---
"""
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="[Bb]ody"):
            parse_skill_md(path)

    def test_runtime_missing_driver_raises(self, tmp_path: Path) -> None:
        content = """\
---
name: bad-runtime
description: Missing runtime driver.
runtime:
  entrypoint: "main.py"
  lockfile: "uv.lock"
---
Body text.
"""
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="driver"):
            parse_skill_md(path)

    def test_runtime_missing_entrypoint_raises(self, tmp_path: Path) -> None:
        content = """\
---
name: bad-runtime
description: Missing runtime entrypoint.
runtime:
  driver: "local/uv"
  lockfile: "uv.lock"
---
Body text.
"""
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="entrypoint"):
            parse_skill_md(path)

    def test_runtime_missing_lockfile_raises(self, tmp_path: Path) -> None:
        content = """\
---
name: bad-runtime
description: Missing runtime lockfile.
runtime:
  driver: "local/uv"
  entrypoint: "main.py"
---
Body text.
"""
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="lockfile"):
            parse_skill_md(path)

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "nonexistent" / "SKILL.md"
        with pytest.raises(FileNotFoundError):
            parse_skill_md(path)

    def test_testing_missing_cases_raises(self, tmp_path: Path) -> None:
        content = """\
---
name: bad-testing
description: Missing testing cases.
testing:
  agents:
    - name: claude
      required_keys: []
---
Body text.
"""
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="cases"):
            parse_skill_md(path)

    def test_testing_agent_missing_name_raises(self, tmp_path: Path) -> None:
        content = """\
---
name: bad-agent
description: Agent without name.
testing:
  cases: "tests/cases.json"
  agents:
    - required_keys: ["KEY"]
---
Body text.
"""
        path = _write_skill_md(tmp_path, content)
        with pytest.raises(ValueError, match="name"):
            parse_skill_md(path)


class TestValidateManifest:
    """Tests for validate_manifest function."""

    def test_valid_manifest_returns_no_errors(self) -> None:
        manifest = SkillManifest(
            name="valid-skill",
            description="A valid skill.",
            license=None,
            compatibility=None,
            metadata=None,
            allowed_tools=None,
            runtime=RuntimeConfig(
                driver="local/uv",
                entrypoint="main.py",
                lockfile="uv.lock",
                env=(),
            ),
            testing=None,
            body="You are a helpful assistant.",
        )
        errors = validate_manifest(manifest)
        assert errors == []

    def test_unsupported_driver_returns_error(self) -> None:
        manifest = SkillManifest(
            name="valid-skill",
            description="A valid skill.",
            license=None,
            compatibility=None,
            metadata=None,
            allowed_tools=None,
            runtime=RuntimeConfig(
                driver="docker",
                entrypoint="main.py",
                lockfile="lock.json",
                env=(),
            ),
            testing=None,
            body="You are a helpful assistant.",
        )
        errors = validate_manifest(manifest)
        assert len(errors) == 1
        assert "docker" in errors[0]

    def test_empty_body_returns_error(self) -> None:
        manifest = SkillManifest(
            name="valid-skill",
            description="A valid skill.",
            license=None,
            compatibility=None,
            metadata=None,
            allowed_tools=None,
            runtime=None,
            testing=None,
            body="",
        )
        errors = validate_manifest(manifest)
        assert any("body" in e.lower() for e in errors)
