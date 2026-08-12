"""Tests for dhub.core.git_repo -- clone and skill discovery."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestCloneRepoSubprocessHardening:
    """Regression tests for the git-clone subprocess safety guarantees.

    A slow or unreachable git host previously hung the CLI indefinitely
    because ``subprocess.run`` was invoked without a ``timeout=``. These
    tests pin in the behaviour that:

    1. Every git invocation is bounded by a timeout.
    2. ``TimeoutExpired`` is translated to a ``RuntimeError`` with a
       sanitised message — the original ``cmd`` argv (which may carry an
       authenticated URL) does not appear in the message.
    """

    def test_clone_runs_with_a_timeout(self) -> None:
        """``subprocess.run`` must be called with a bounded ``timeout=``."""
        completed = MagicMock()
        completed.returncode = 0
        completed.stderr = ""

        with patch("dhub.core.git_repo.subprocess.run", return_value=completed) as run_mock:
            clone_repo("https://github.com/example/repo.git")

        run_mock.assert_called_once()
        _args, kwargs = run_mock.call_args
        assert kwargs.get("timeout"), "git clone must pass a timeout to subprocess.run"
        assert kwargs["timeout"] > 0

    def test_clone_timeout_raises_sanitised_runtime_error(self, tmp_path: Path) -> None:
        """A ``TimeoutExpired`` becomes a ``RuntimeError`` without leaking argv."""

        def _raise(*_args, **kwargs):
            raise subprocess.TimeoutExpired(
                cmd=["git", "clone", "https://x-access-token:SECRET@github.com/o/r.git"],
                timeout=kwargs.get("timeout", 0),
            )

        with (
            patch("dhub.core.git_repo.subprocess.run", side_effect=_raise),
            pytest.raises(RuntimeError) as exc_info,
        ):
            clone_repo("https://x-access-token:SECRET@github.com/o/r.git")

        message = str(exc_info.value)
        assert "timed out" in message
        # The secret in the URL must not appear in the user-facing message.
        assert "SECRET" not in message

    def test_clone_failure_cleans_up_tempdir(self, tmp_path: Path) -> None:
        """A non-zero exit triggers cleanup of the tempdir so /tmp does not fill."""

        completed = MagicMock()
        completed.returncode = 128
        completed.stderr = "fatal: repository not found"

        # Track the directory clone_repo creates so we can assert it is removed.
        created: list[Path] = []
        real_mkdtemp = __import__("tempfile").mkdtemp

        def _spy_mkdtemp(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            created.append(Path(path))
            return path

        with (
            patch("dhub.core.git_repo.subprocess.run", return_value=completed),
            patch("dhub.core.git_repo.tempfile.mkdtemp", side_effect=_spy_mkdtemp),
            pytest.raises(RuntimeError, match="git clone failed"),
        ):
            clone_repo("https://github.com/example/does-not-exist.git")

        assert created, "tempfile.mkdtemp was not invoked"
        assert not created[0].exists(), "temp directory should be removed on clone failure"
