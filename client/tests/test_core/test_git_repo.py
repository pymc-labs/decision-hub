"""Tests for dhub.core.git_repo -- clone and skill discovery."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dhub.core.git_repo import _GIT_TIMEOUT_SECONDS, _run_git, clone_repo, discover_skills


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


class TestRunGitTimeout:
    """Hung git remotes must not hang the CLI forever."""

    def test_run_git_passes_timeout_to_subprocess(self) -> None:
        """_run_git forwards the module timeout to subprocess.run."""
        with patch("dhub.core.git_repo.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "--version"], returncode=0, stdout="", stderr=""
            )

            _run_git(["git", "--version"])

            kwargs = mock_run.call_args.kwargs
            assert kwargs["timeout"] == _GIT_TIMEOUT_SECONDS
            assert kwargs["capture_output"] is True
            assert kwargs["text"] is True

    def test_run_git_converts_timeout_to_runtime_error(self) -> None:
        """A subprocess timeout becomes a RuntimeError with a clean message."""
        with patch("dhub.core.git_repo.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git", "clone"], timeout=_GIT_TIMEOUT_SECONDS)

            with pytest.raises(RuntimeError, match="timed out"):
                _run_git(["git", "clone", "https://example.invalid/repo.git"])

    def test_clone_repo_cleans_tmpdir_on_timeout(self, tmp_path: Path) -> None:
        """A timed-out clone deletes its temp dir instead of leaving a partial clone."""
        created_paths: list[Path] = []

        original_mkdtemp = __import__("tempfile").mkdtemp

        def tracking_mkdtemp(*args, **kwargs):
            path = original_mkdtemp(*args, **kwargs)
            created_paths.append(Path(path))
            return path

        with (
            patch("dhub.core.git_repo.tempfile.mkdtemp", side_effect=tracking_mkdtemp),
            patch("dhub.core.git_repo.subprocess.run") as mock_run,
        ):
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git", "clone"], timeout=_GIT_TIMEOUT_SECONDS)

            with pytest.raises(RuntimeError):
                clone_repo("https://example.invalid/repo.git")

        assert created_paths, "expected tempfile.mkdtemp to be called"
        assert not created_paths[0].exists()
