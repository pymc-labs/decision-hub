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
    """clone_repo must never block indefinitely on an unresponsive remote."""

    def test_clone_timeout_raises_runtime_error(self) -> None:
        """A hung `git clone` surfaces as a friendly RuntimeError, not TimeoutExpired."""
        with patch("dhub.core.git_repo.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git", "clone"], timeout=300)
            with pytest.raises(RuntimeError, match="timed out"):
                clone_repo("https://github.com/example/hangs.git")

    def test_clone_passes_timeout_to_subprocess(self) -> None:
        """The subprocess call is invoked with a bounded timeout keyword."""
        with patch("dhub.core.git_repo.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["git", "clone"], returncode=0, stdout="", stderr=""
            )
            clone_repo("https://github.com/example/repo.git")
            # Any positive timeout is fine — the point is that we pass one.
            _, kwargs = mock_run.call_args
            assert kwargs.get("timeout", 0) > 0

    def test_clone_cleans_tmpdir_on_timeout(self, tmp_path: Path) -> None:
        """Timed-out clones don't leak stale directories under /tmp."""
        seen_paths: list[Path] = []

        def _fake_run(cmd, **kwargs):
            # Grab the destination path git was told to write to so we can
            # assert on it after the failure surfaces.
            seen_paths.append(Path(cmd[-1]).parent)
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"))

        with (
            patch("dhub.core.git_repo.subprocess.run", side_effect=_fake_run),
            pytest.raises(RuntimeError),
        ):
            clone_repo("https://github.com/example/hangs.git")

        assert seen_paths, "expected clone_repo to invoke git at least once"
        assert not seen_paths[0].exists(), "tmp dir should be removed after timeout"
