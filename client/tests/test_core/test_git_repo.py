"""Tests for dhub.core.git_repo -- clone and skill discovery."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dhub.core.git_repo import _sanitize, clone_repo, discover_skills


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


class TestSanitize:
    """URLs with credentials must never appear in error messages we surface."""

    def test_strips_password_from_https_url(self) -> None:
        text = "fatal: could not read from https://user:ghp_TOKEN@github.com/foo/bar"
        assert _sanitize(text) == "fatal: could not read from https://[REDACTED]@github.com/foo/bar"

    def test_strips_token_only_userinfo(self) -> None:
        text = "clone https://ghp_TOKEN123@github.com/foo"
        assert _sanitize(text) == "clone https://[REDACTED]@github.com/foo"

    def test_strips_ssh_userinfo(self) -> None:
        text = "cannot resolve ssh://git@github.com/foo/bar"
        assert _sanitize(text) == "cannot resolve ssh://[REDACTED]@github.com/foo/bar"

    def test_passes_through_clean_url(self) -> None:
        text = "cloning into https://github.com/foo/bar"
        assert _sanitize(text) == text


class TestCloneRepo:
    """clone_repo hardening: sanitize errors and honour timeouts."""

    def test_clone_failure_sanitizes_credential_url(self, tmp_path: Path) -> None:
        stderr = "fatal: repository https://ghp_leaked@github.com/foo/bar not found"

        def fake_run(*_args, **_kwargs):
            return subprocess.CompletedProcess(args=[], returncode=128, stdout="", stderr=stderr)

        with (
            patch("dhub.core.git_repo.subprocess.run", side_effect=fake_run),
            pytest.raises(RuntimeError) as exc_info,
        ):
            clone_repo("https://ghp_leaked@github.com/foo/bar")

        message = str(exc_info.value)
        assert "ghp_leaked" not in message
        assert "[REDACTED]" in message

    def test_timeout_is_reraised_as_sanitized_runtime_error(self) -> None:
        def fake_run(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd=["git", "clone"], timeout=1)

        with (
            patch("dhub.core.git_repo.subprocess.run", side_effect=fake_run),
            pytest.raises(RuntimeError) as exc_info,
        ):
            clone_repo("https://ghp_leaked@github.com/foo/bar")

        message = str(exc_info.value)
        assert "timed out" in message
        # TimeoutExpired repr includes cmd argv which could contain the URL;
        # we surface only the sanitized "git clone" prefix.
        assert "ghp_leaked" not in message

    def test_subprocess_run_gets_timeout(self) -> None:
        """Guardrail: the wrapper must pass a bounded ``timeout=`` to subprocess.run."""
        called_kwargs: dict = {}

        def fake_run(_cmd, **kwargs):
            called_kwargs.update(kwargs)
            return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="err")

        with (
            patch("dhub.core.git_repo.subprocess.run", side_effect=fake_run),
            pytest.raises(RuntimeError),
        ):
            clone_repo("https://github.com/foo/bar")

        assert "timeout" in called_kwargs
        assert isinstance(called_kwargs["timeout"], int)
        assert called_kwargs["timeout"] > 0
