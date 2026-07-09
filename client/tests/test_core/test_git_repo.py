"""Tests for dhub.core.git_repo -- clone and skill discovery."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dhub.core.git_repo import clone_repo, discover_skills


class TestDiscoverSkills:
    def _write_skill_md(self, directory: Path, name: str = "test-skill") -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: A test skill\n---\nBody text\n")

    def test_discovers_single_skill_at_root(self, tmp_path: Path) -> None:
        self._write_skill_md(tmp_path)
        result = discover_skills(tmp_path)
        assert result == [tmp_path]

    def test_discovers_skills_in_subdirectories(self, tmp_path: Path) -> None:
        self._write_skill_md(tmp_path / "skills" / "alpha", name="alpha")
        self._write_skill_md(tmp_path / "skills" / "beta", name="beta")
        result = discover_skills(tmp_path)
        assert len(result) == 2
        names = {p.name for p in result}
        assert names == {"alpha", "beta"}

    def test_discovers_deeply_nested_skills(self, tmp_path: Path) -> None:
        self._write_skill_md(tmp_path / "a" / "b" / "c" / "deep-skill", name="deep-skill")
        result = discover_skills(tmp_path)
        assert len(result) == 1
        assert result[0].name == "deep-skill"

    def test_skips_hidden_directories(self, tmp_path: Path) -> None:
        self._write_skill_md(tmp_path / ".hidden" / "secret-skill", name="secret-skill")
        self._write_skill_md(tmp_path / "visible", name="visible")
        result = discover_skills(tmp_path)
        assert len(result) == 1
        assert result[0].name == "visible"

    def test_skips_pycache_directories(self, tmp_path: Path) -> None:
        self._write_skill_md(tmp_path / "__pycache__" / "cached", name="cached")
        self._write_skill_md(tmp_path / "real-skill", name="real-skill")
        result = discover_skills(tmp_path)
        assert len(result) == 1
        assert result[0].name == "real-skill"

    def test_skips_node_modules(self, tmp_path: Path) -> None:
        self._write_skill_md(tmp_path / "node_modules" / "pkg", name="pkg")
        self._write_skill_md(tmp_path / "my-skill", name="my-skill")
        result = discover_skills(tmp_path)
        assert len(result) == 1
        assert result[0].name == "my-skill"

    def test_skips_invalid_skill_md(self, tmp_path: Path) -> None:
        # Valid skill
        self._write_skill_md(tmp_path / "good-skill", name="good-skill")
        # Invalid SKILL.md (missing required fields)
        bad_dir = tmp_path / "bad-skill"
        bad_dir.mkdir()
        (bad_dir / "SKILL.md").write_text("not valid yaml frontmatter\n")
        result = discover_skills(tmp_path)
        assert len(result) == 1
        assert result[0].name == "good-skill"

    def test_returns_empty_when_no_skills(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Just a readme\n")
        result = discover_skills(tmp_path)
        assert result == []

    def test_returns_sorted_results(self, tmp_path: Path) -> None:
        self._write_skill_md(tmp_path / "charlie", name="charlie")
        self._write_skill_md(tmp_path / "alpha", name="alpha")
        self._write_skill_md(tmp_path / "bravo", name="bravo")
        result = discover_skills(tmp_path)
        names = [p.name for p in result]
        assert names == sorted(names)

    def test_does_not_follow_directory_symlink_cycle(self, tmp_path: Path) -> None:
        """A cyclic directory symlink used to trip Python's recursion limit."""
        real = tmp_path / "real"
        self._write_skill_md(real / "skill-a", name="skill-a")

        # Introduce a cycle: real/loop -> real (points back at itself).
        (real / "loop").symlink_to(real, target_is_directory=True)

        result = discover_skills(tmp_path)
        # We must terminate and only surface the real skill once.
        assert len(result) == 1
        assert result[0].name == "skill-a"

    def test_does_not_follow_symlink_to_outside_tree(self, tmp_path: Path) -> None:
        """A symlink to a directory outside the tree must NOT double-publish its skills."""
        outside = tmp_path / "outside"
        self._write_skill_md(outside / "external-skill", name="external-skill")

        tree = tmp_path / "tree"
        self._write_skill_md(tree / "own-skill", name="own-skill")
        (tree / "link_to_outside").symlink_to(outside, target_is_directory=True)

        result = discover_skills(tree)
        # Only the skills that physically live in `tree` should surface.
        assert {p.name for p in result} == {"own-skill"}


class TestCloneRepoTimeout:
    """clone_repo must bound git subprocess calls so a slow/hostile remote can't hang the CLI."""

    def test_timeout_raises_runtime_error(self, tmp_path: Path) -> None:
        # Simulate a git subprocess that never returns.
        def slow_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 1))

        with (
            patch("dhub.core.git_repo.subprocess.run", side_effect=slow_run),
            pytest.raises(RuntimeError, match="timed out"),
        ):
            clone_repo("https://example.invalid/repo.git")

    def test_passes_timeout_to_subprocess(self) -> None:
        """The subprocess call must actually receive timeout= so it can't hang."""
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured.update(kwargs)
            import types

            return types.SimpleNamespace(returncode=0, stderr="", stdout="")

        with patch("dhub.core.git_repo.subprocess.run", side_effect=fake_run):
            clone_repo("https://example.invalid/repo.git")

        assert captured.get("timeout") is not None
        assert captured["timeout"] > 0
