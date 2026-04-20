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


class TestCloneRepoTimeout:
    """``clone_repo`` must never block the CLI indefinitely.

    Without a ``timeout=`` on the underlying ``subprocess.run`` call a
    hanging ``git clone`` (bad URL, dead mirror, firewall) would freeze
    the session forever.  These tests pin the timeout + friendly-error
    contract by simulating the subprocess outcomes.
    """

    def test_timeout_surfaces_actionable_error(self) -> None:
        timeout = subprocess.TimeoutExpired(cmd=["git", "clone", "url"], timeout=300)
        with (
            patch("dhub.core.git_repo.subprocess.run", side_effect=timeout),
            pytest.raises(RuntimeError) as exc,
        ):
            clone_repo("https://example.com/repo.git")
        msg = str(exc.value)
        assert "timed out" in msg
        # Error text should give the user a concrete next action.
        assert "network" in msg.lower() or "url" in msg.lower()

    def test_missing_git_executable_raises_friendly_error(self) -> None:
        with (
            patch("dhub.core.git_repo.subprocess.run", side_effect=FileNotFoundError),
            pytest.raises(RuntimeError) as exc,
        ):
            clone_repo("https://example.com/repo.git")
        assert "git executable not found" in str(exc.value).lower()

    def test_subprocess_run_invoked_with_timeout(self, tmp_path: Path) -> None:
        """The timeout argument must actually be forwarded."""

        # Simulate a successful clone so clone_repo returns cleanly.
        def _fake_run(cmd, **kwargs):
            assert "timeout" in kwargs and kwargs["timeout"] > 0
            # Pretend the clone worked.
            repo_path = Path(cmd[-1])
            repo_path.mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        with patch("dhub.core.git_repo.subprocess.run", side_effect=_fake_run):
            result = clone_repo("https://example.com/repo.git")
        assert result.is_dir()
