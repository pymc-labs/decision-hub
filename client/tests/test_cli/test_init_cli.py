"""Tests for dhub init command."""

from pathlib import Path

from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


class TestInitCommand:

    def test_init_creates_skill_in_current_dir(self, tmp_path: Path) -> None:
        """init in current dir creates SKILL.md and src/."""
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

    def test_init_refuses_existing_skill_md(self, tmp_path: Path) -> None:
        """init refuses to overwrite an existing SKILL.md."""
        (tmp_path / "SKILL.md").write_text("existing content")

        result = runner.invoke(
            app,
            ["init"],
            input="my-skill\nA skill\n",
        )

        # When path is "." and SKILL.md exists, it should fail
        # (but name creates subdir, so only fails if the subdir also has SKILL.md)
        # Test the explicit case: init in a dir that already has SKILL.md
        monkeypatch_dir = tmp_path / "sub"
        monkeypatch_dir.mkdir()
        (monkeypatch_dir / "SKILL.md").write_text("existing")

        result = runner.invoke(
            app,
            ["init", str(tmp_path)],
            input="sub\nA skill\n",
        )

        assert result.exit_code == 1
        assert "already exists" in result.output

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
