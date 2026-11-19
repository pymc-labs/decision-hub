"""Tests for dhub init command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from dhub.cli.app import app
from dhub_core.manifest import parse_skill_md

runner = CliRunner(env={"DHUB_NO_UPDATE_CHECK": "1"})


class TestInitCommand:
    def test_init_creates_skill_under_explicit_parent(self, tmp_path: Path) -> None:
        """An explicit parent gets a subdirectory named for the skill."""
        result = runner.invoke(
            app,
            ["init", str(tmp_path)],
            input="my-skill\nA helpful skill\n",
        )

        assert result.exit_code == 0
        skill_dir = tmp_path / "my-skill"
        assert (skill_dir / "SKILL.md").exists()
        assert (skill_dir / "src").is_dir()

        content = (skill_dir / "SKILL.md").read_text()
        assert "name: my-skill" in content
        assert "A helpful skill" in content

    def test_init_default_path(self, tmp_path: Path, monkeypatch) -> None:
        """init without path argument uses current directory."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(
            app,
            ["init"],
            input="test-skill\nTest description\n",
        )

        assert result.exit_code == 0
        assert (tmp_path / "SKILL.md").exists()
        assert (tmp_path / "src").is_dir()

    def test_init_rejects_invalid_name(self, tmp_path: Path) -> None:
        """init rejects names that fail validation."""
        result = runner.invoke(
            app,
            ["init", str(tmp_path)],
            input="INVALID NAME!\nSome description\n",
        )

        assert result.exit_code != 0

    @pytest.mark.parametrize(
        ("args", "destination"), [([], "."), (["."], "."), (["skills", "--name", "my-skill"], "skills/my-skill")]
    )
    def test_init_refuses_existing_skill_md(self, tmp_path: Path, monkeypatch, args, destination) -> None:
        monkeypatch.chdir(tmp_path)
        skill_dir = tmp_path / destination
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("existing content")

        result = runner.invoke(app, ["init", *args])

        assert result.exit_code == 1
        assert "already exists" in result.output
        assert "Skill name" not in result.output
        assert "Short description" not in result.output
        assert skill_md.read_text() == "existing content"
        assert list(skill_dir.iterdir()) == [skill_md]

    def test_init_body_contains_heading(self, tmp_path: Path) -> None:
        """Generated SKILL.md body contains a heading with the skill name."""
        result = runner.invoke(
            app,
            ["init", str(tmp_path)],
            input="cool-tool\nDoes cool things\n",
        )

        assert result.exit_code == 0
        content = (tmp_path / "cool-tool" / "SKILL.md").read_text()
        assert "# cool-tool" in content

    def test_init_description_with_double_quote_produces_valid_yaml(self, tmp_path: Path) -> None:
        """A description containing a `"` must not corrupt the SKILL.md frontmatter.

        Historical bug: `f'description: "{description}"'` produced
        `description: "Say "hello""` for the input `Say "hello"`, which is
        invalid YAML. The freshly scaffolded skill then failed to parse.
        """
        result = runner.invoke(
            app,
            ["init", str(tmp_path)],
            input='cool-tool\nSay "hello" from the shell\n',
        )

        assert result.exit_code == 0

        # Parse the frontmatter to verify it's valid YAML end-to-end.
        skill_md_path = tmp_path / "cool-tool" / "SKILL.md"
        manifest = parse_skill_md(skill_md_path)
        assert manifest.name == "cool-tool"
        assert manifest.description == 'Say "hello" from the shell'

    def test_init_description_with_backslash_produces_valid_yaml(self, tmp_path: Path) -> None:
        """Backslashes in the description must not break YAML parsing."""
        result = runner.invoke(
            app,
            ["init", str(tmp_path)],
            input="cool-tool\nUse C:\\Windows\\path here\n",
        )

        assert result.exit_code == 0
        skill_md_path = tmp_path / "cool-tool" / "SKILL.md"
        manifest = parse_skill_md(skill_md_path)
        assert manifest.description == "Use C:\\Windows\\path here"

    def test_init_shows_friendly_error_on_invalid_name(self, tmp_path: Path) -> None:
        """Invalid names must produce a Rich error, not a raw Python traceback."""
        result = runner.invoke(
            app,
            ["init", str(tmp_path)],
            input="Invalid Upper\nA description\n",
        )
        assert result.exit_code == 1
        # No traceback — the ValueError from validate_skill_name must be caught.
        assert "Traceback" not in (result.output + str(result.exception or ""))

    @pytest.mark.parametrize(("path_args", "destination"), [([], "."), (["."], "."), (["skills"], "skills/on")])
    def test_init_with_flags_needs_no_stdin(self, tmp_path: Path, monkeypatch, path_args, destination) -> None:
        monkeypatch.chdir(tmp_path)
        description = 'Say "hello": C:\\work\n---\nNext line 🚀\n'
        result = runner.invoke(app, ["init", *path_args, "--name", "on", "--description", description])

        assert result.exit_code == 0, result.output
        assert "Skill name" not in result.output
        assert "Short description" not in result.output
        assert "Created skill project at" in result.output
        skill_dir = tmp_path / destination
        assert (skill_dir / "src").is_dir()
        manifest = parse_skill_md(skill_dir / "SKILL.md")
        assert manifest.name == "on"
        assert manifest.description == description

    @pytest.mark.parametrize(
        ("options", "answer", "prompt", "skipped"),
        [
            (["--name", "my-skill"], "A helpful skill", "Short description", "Skill name"),
            (["--description", "A helpful skill"], "my-skill", "Skill name", "Short description"),
        ],
    )
    def test_init_prompts_only_for_missing_field(self, tmp_path, options, answer, prompt, skipped) -> None:
        result = runner.invoke(app, ["init", str(tmp_path), *options], input=answer + "\n")

        assert result.exit_code == 0, result.output
        assert prompt in result.output
        assert skipped not in result.output
        manifest = parse_skill_md(tmp_path / "my-skill/SKILL.md")
        assert manifest.name == "my-skill"
        assert manifest.description == "A helpful skill"

    @pytest.mark.parametrize(
        ("options", "error"),
        [
            (["--name", ""], "Invalid skill name"),
            (["--name", "my-skill\n"], "Invalid skill name"),
            (["--name", "INVALID"], "Invalid skill name"),
            (["--description", ""], "Description"),
            (["--description", " \t\n "], "Description"),
            (["--description", "x" * 1025], "Description"),
        ],
    )
    def test_init_rejects_invalid_flags_before_writing(self, tmp_path, options, error) -> None:
        result = runner.invoke(app, ["init", str(tmp_path / "skills"), *options])

        assert result.exit_code == 1
        assert error in result.output
        assert not (tmp_path / "skills").exists()

    def test_init_accepts_maximum_length_description(self, tmp_path: Path) -> None:
        description = "x" * 1024
        result = runner.invoke(app, ["init", str(tmp_path), "--name", "my-skill", "--description", description])

        assert result.exit_code == 0, result.output
        assert parse_skill_md(tmp_path / "my-skill/SKILL.md").description == description

    def test_init_leaves_existing_src_file_intact(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        src_file = tmp_path / "src"
        src_file.write_text("existing content")

        result = runner.invoke(app, ["init", "--name", "my-skill", "--description", "A helpful skill"])

        assert result.exit_code == 1
        assert "src" in result.output
        assert src_file.read_text() == "existing content"
        assert list(tmp_path.iterdir()) == [src_file]
