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


class TestCloneRepo:
    """Behaviour of clone_repo around timeouts, errors, and cleanup."""

    def test_clone_passes_timeout_to_subprocess(self) -> None:
        """All git invocations must include `timeout=` so the CLI cannot hang forever."""
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("dhub.core.git_repo.subprocess.run", return_value=completed) as run:
            clone_repo("https://example.com/repo.git")
        assert run.call_count == 1
        _, kwargs = run.call_args
        assert "timeout" in kwargs, "subprocess.run must be called with a timeout"
        assert kwargs["timeout"] > 0

    def test_clone_timeout_raises_runtime_error(self, tmp_path: Path) -> None:
        """TimeoutExpired must surface as RuntimeError (not bubble up as a subprocess error)."""
        with (
            patch(
                "dhub.core.git_repo.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["git", "clone"], timeout=120),
            ),
            pytest.raises(RuntimeError, match="timed out"),
        ):
            clone_repo("https://example.com/slow.git")

    def test_clone_failure_cleans_up_tmp_dir(self) -> None:
        """A failed clone must not leak dhub-repo-* directories under tempdir."""
        import tempfile

        failed = subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr="fatal: repository not found")
        before = set(Path(tempfile.gettempdir()).glob("dhub-repo-*"))
        with (
            patch("dhub.core.git_repo.subprocess.run", return_value=failed),
            pytest.raises(RuntimeError, match="git clone failed"),
        ):
            clone_repo("https://example.com/missing.git")
        after = set(Path(tempfile.gettempdir()).glob("dhub-repo-*"))
        assert after == before, "tmp dir should have been removed on failure"

    def test_clone_with_sha_does_two_calls(self) -> None:
        """SHA refs trigger a full clone followed by a separate checkout."""
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("dhub.core.git_repo.subprocess.run", return_value=completed) as run:
            clone_repo("https://example.com/repo.git", ref="abc1234")
        assert run.call_count == 2
        assert run.call_args_list[0][0][0][:2] == ["git", "clone"]
        assert run.call_args_list[1][0][0][:2] == ["git", "checkout"]
        # Both invocations must honour the timeout bound.
        for _, kwargs in run.call_args_list:
            assert "timeout" in kwargs and kwargs["timeout"] > 0
