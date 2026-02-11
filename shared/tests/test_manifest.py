"""Tests for dhub_core.manifest — SKILL.md parser and validator."""

import pytest

from dhub_core.manifest import (
    parse_dependencies,
    parse_evals,
    parse_frontmatter_yaml,
    parse_runtime,
    parse_testing,
    split_frontmatter,
    validate_manifest,
)
from dhub_core.models import (
    DependencySpec,
    EvalConfig,
    RuntimeConfig,
    SkillManifest,
    TestingConfig,
)

# ---------------------------------------------------------------------------
# split_frontmatter
# ---------------------------------------------------------------------------


class TestSplitFrontmatter:
    """split_frontmatter extracts YAML frontmatter and body from SKILL.md content."""

    def test_standard(self) -> None:
        content = "---\nname: my-skill\n---\nBody text here."
        fm, body = split_frontmatter(content)
        assert fm == "name: my-skill"
        assert body == "Body text here."

    def test_leading_blank_lines(self) -> None:
        content = "\n\n---\nname: my-skill\n---\nBody."
        fm, body = split_frontmatter(content)
        assert fm == "name: my-skill"
        assert body == "Body."

    def test_no_opening_delimiter(self) -> None:
        with pytest.raises(ValueError, match="must start with ---"):
            split_frontmatter("name: my-skill\n---\nBody.")

    def test_no_closing_delimiter(self) -> None:
        with pytest.raises(ValueError, match="closing ---"):
            split_frontmatter("---\nname: my-skill\nBody without closing.")


# ---------------------------------------------------------------------------
# parse_frontmatter_yaml
# ---------------------------------------------------------------------------


class TestParseFrontmatterYaml:
    """parse_frontmatter_yaml parses YAML with fallback for unquoted colons."""

    def test_standard_yaml(self) -> None:
        result = parse_frontmatter_yaml("name: my-skill\ndescription: A tool")
        assert result == {"name": "my-skill", "description": "A tool"}

    def test_fallback_unquoted_colons(self) -> None:
        yaml_str = "name: my-skill\ndescription: Use this: it's great"
        result = parse_frontmatter_yaml(yaml_str)
        assert result["name"] == "my-skill"
        assert "great" in result["description"]

    def test_unparseable_yaml(self) -> None:
        import yaml

        with pytest.raises(yaml.YAMLError):
            parse_frontmatter_yaml(":\n  :\n    - [invalid")


# ---------------------------------------------------------------------------
# parse_runtime
# ---------------------------------------------------------------------------


class TestParseRuntime:
    """parse_runtime handles new format, old format, and edge cases."""

    def test_none_input(self) -> None:
        assert parse_runtime(None) is None

    def test_new_format(self) -> None:
        data = {
            "language": "python",
            "entrypoint": "main.py",
            "dependencies": {
                "system": ["git"],
                "package_manager": "uv",
                "packages": ["requests"],
                "lockfile": "uv.lock",
            },
            "env": ["API_KEY"],
            "capabilities": ["network"],
        }
        result = parse_runtime(data)
        assert isinstance(result, RuntimeConfig)
        assert result.language == "python"
        assert result.entrypoint == "main.py"
        assert result.env == ("API_KEY",)
        assert result.capabilities == ("network",)
        assert result.dependencies is not None
        assert result.dependencies.system == ("git",)
        assert result.dependencies.package_manager == "uv"
        assert result.dependencies.packages == ("requests",)
        assert result.dependencies.lockfile == "uv.lock"

    def test_old_format(self) -> None:
        data = {
            "driver": "local/uv",
            "entrypoint": "run.py",
            "lockfile": "uv.lock",
        }
        result = parse_runtime(data)
        assert isinstance(result, RuntimeConfig)
        assert result.language == "python"
        assert result.entrypoint == "run.py"
        assert result.dependencies is not None
        assert result.dependencies.lockfile == "uv.lock"
        assert result.dependencies.package_manager == "uv"

    def test_old_format_maps_driver_to_language(self) -> None:
        data = {
            "driver": "local/uv",
            "entrypoint": "run.py",
            "lockfile": "uv.lock",
        }
        result = parse_runtime(data)
        assert result is not None
        assert result.language == "python"

    def test_missing_entrypoint(self) -> None:
        with pytest.raises(ValueError, match="entrypoint"):
            parse_runtime({"language": "python"})

    def test_non_dict_input(self) -> None:
        with pytest.raises(ValueError, match="must be a mapping"):
            parse_runtime("not-a-dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# parse_dependencies
# ---------------------------------------------------------------------------


class TestParseDependencies:
    """parse_dependencies handles full specs, defaults, and errors."""

    def test_none_input(self) -> None:
        assert parse_dependencies(None) is None

    def test_full_spec(self) -> None:
        data = {
            "system": ["libffi", "git"],
            "package_manager": "uv",
            "packages": ["requests", "click"],
            "lockfile": "uv.lock",
        }
        result = parse_dependencies(data)
        assert isinstance(result, DependencySpec)
        assert result.system == ("libffi", "git")
        assert result.package_manager == "uv"
        assert result.packages == ("requests", "click")
        assert result.lockfile == "uv.lock"

    def test_defaults_for_missing_optional_fields(self) -> None:
        result = parse_dependencies({})
        assert isinstance(result, DependencySpec)
        assert result.system == ()
        assert result.package_manager == ""
        assert result.packages == ()
        assert result.lockfile is None

    def test_non_dict_input(self) -> None:
        with pytest.raises(ValueError, match="must be a mapping"):
            parse_dependencies("bad")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# parse_evals
# ---------------------------------------------------------------------------


class TestParseEvals:
    """parse_evals validates required fields."""

    def test_none_input(self) -> None:
        assert parse_evals(None) is None

    def test_valid(self) -> None:
        data = {"agent": "claude", "judge_model": "gpt-4o"}
        result = parse_evals(data)
        assert isinstance(result, EvalConfig)
        assert result.agent == "claude"
        assert result.judge_model == "gpt-4o"

    def test_missing_agent(self) -> None:
        with pytest.raises(ValueError, match="agent"):
            parse_evals({"judge_model": "gpt-4o"})

    def test_missing_judge_model(self) -> None:
        with pytest.raises(ValueError, match="judge_model"):
            parse_evals({"agent": "claude"})


# ---------------------------------------------------------------------------
# parse_testing (legacy)
# ---------------------------------------------------------------------------


class TestParseTesting:
    """parse_testing validates legacy testing config."""

    def test_none_input(self) -> None:
        assert parse_testing(None) is None

    def test_valid(self) -> None:
        data = {
            "cases": "tests/cases.yaml",
            "agents": [
                {"name": "claude", "required_keys": ["ANTHROPIC_API_KEY"]},
            ],
        }
        result = parse_testing(data)
        assert isinstance(result, TestingConfig)
        assert result.cases == "tests/cases.yaml"
        assert len(result.agents) == 1
        assert result.agents[0].name == "claude"
        assert result.agents[0].required_keys == ("ANTHROPIC_API_KEY",)

    def test_missing_cases(self) -> None:
        with pytest.raises(ValueError, match="cases"):
            parse_testing({"agents": []})


# ---------------------------------------------------------------------------
# validate_manifest
# ---------------------------------------------------------------------------


class TestValidateManifest:
    """validate_manifest returns error lists for invalid manifests."""

    @staticmethod
    def _make_manifest(**overrides) -> SkillManifest:
        defaults = {
            "name": "valid-skill",
            "description": "A valid description",
            "license": None,
            "compatibility": None,
            "metadata": None,
            "allowed_tools": None,
            "runtime": None,
            "evals": None,
            "body": "System prompt body",
        }
        defaults.update(overrides)
        return SkillManifest(**defaults)

    def test_valid_manifest(self) -> None:
        manifest = self._make_manifest()
        assert validate_manifest(manifest) == []

    def test_invalid_name(self) -> None:
        manifest = self._make_manifest(name="INVALID")
        errors = validate_manifest(manifest)
        assert any("name" in e.lower() for e in errors)

    def test_missing_body(self) -> None:
        manifest = self._make_manifest(body="")
        errors = validate_manifest(manifest)
        assert any("body" in e.lower() for e in errors)

    def test_unsupported_runtime_language(self) -> None:
        runtime = RuntimeConfig(language="ruby", entrypoint="main.rb")
        manifest = self._make_manifest(runtime=runtime)
        errors = validate_manifest(manifest)
        assert any("ruby" in e.lower() for e in errors)
