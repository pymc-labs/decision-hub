"""Tests for dhub.core.git_repo -- clone and skill discovery."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dhub.core.git_repo import _redact_credentials, clone_repo, discover_skills


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


class TestRedactCredentials:
    def test_strips_token_userinfo_from_https_url(self) -> None:
        text = "fatal: could not read from https://x-access-token:ghp_SECRET@github.com/o/r.git"
        redacted = _redact_credentials(text)
        assert "ghp_SECRET" not in redacted
        assert "x-access-token" not in redacted
        assert "https://github.com/o/r.git" in redacted

    def test_strips_basic_auth_userinfo(self) -> None:
        assert "hunter2" not in _redact_credentials("clone https://user:hunter2@example.com/r")

    def test_leaves_credential_free_urls_untouched(self) -> None:
        text = "fatal: repository 'https://github.com/o/r.git' not found"
        assert _redact_credentials(text) == text


class TestCloneErrorHandling:
    def test_clone_failure_redacts_credentials_in_error(self) -> None:
        """A token embedded in the clone URL must never reach the raised error."""
        failed = subprocess.CompletedProcess(
            args=[],
            returncode=128,
            stdout="",
            stderr="fatal: Authentication failed for https://x-access-token:ghp_SECRET@github.com/o/r.git",
        )
        with (
            patch("dhub.core.git_repo.subprocess.run", return_value=failed),
            pytest.raises(RuntimeError) as exc_info,
        ):
            clone_repo("https://x-access-token:ghp_SECRET@github.com/o/r.git")
        assert "ghp_SECRET" not in str(exc_info.value)

    def test_clone_timeout_raises_clean_error(self) -> None:
        """A hung clone must raise a timeout RuntimeError rather than block forever."""
        with (
            patch(
                "dhub.core.git_repo.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="git clone", timeout=300),
            ),
            pytest.raises(RuntimeError, match="timed out"),
        ):
            clone_repo("https://github.com/o/r.git")
