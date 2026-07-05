"""Tests for dhub.core.git_repo -- clone and skill discovery."""

import contextlib
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dhub.core.git_repo import _GIT_TIMEOUT_SECONDS, clone_repo, discover_skills


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


class TestCloneRepoHardening:
    """Ensure clone_repo cannot be abused by a hostile URL and cannot hang."""

    def test_clone_places_dashdash_before_repo_url(self) -> None:
        """A URL like '--upload-pack=foo' must not be parsed as a git option."""
        with patch("dhub.core.git_repo.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            # Some code paths after subprocess may still raise (e.g. mkdir
            # ordering in the fake); we only care about how subprocess.run
            # was invoked.
            with contextlib.suppress(RuntimeError):
                clone_repo("--upload-pack=/bin/false")
        cmd = mock_run.call_args.args[0]
        assert "--" in cmd, "clone command must include -- end-of-options separator"
        # -- must come before the (hostile) URL positional
        assert cmd.index("--") < cmd.index("--upload-pack=/bin/false")

    def test_clone_uses_timeout(self) -> None:
        """subprocess.run must be called with a timeout so we never hang."""
        with patch("dhub.core.git_repo.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            with contextlib.suppress(RuntimeError):
                clone_repo("https://github.com/example/repo.git")
        kwargs = mock_run.call_args.kwargs
        assert kwargs.get("timeout") == _GIT_TIMEOUT_SECONDS

    def test_clone_disables_credential_prompt(self) -> None:
        """GIT_TERMINAL_PROMPT=0 must be set so credential prompts fail fast."""
        with patch("dhub.core.git_repo.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            with contextlib.suppress(RuntimeError):
                clone_repo("https://github.com/example/repo.git")
        env = mock_run.call_args.kwargs["env"]
        assert env.get("GIT_TERMINAL_PROMPT") == "0"

    def test_clone_timeout_raises_runtime_error(self) -> None:
        """TimeoutExpired is caught and surfaced as a friendly RuntimeError."""
        with patch("dhub.core.git_repo.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["git"], timeout=1)
            with pytest.raises(RuntimeError, match="timed out"):
                clone_repo("https://github.com/example/repo.git")
