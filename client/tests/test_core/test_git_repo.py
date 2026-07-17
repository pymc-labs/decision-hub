"""Tests for dhub.core.git_repo -- clone and skill discovery."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dhub.core.git_repo import (
    _redact_url_in_text,
    _strip_credentials,
    clone_repo,
    discover_skills,
)


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


class TestCredentialScrubbing:
    """The clone helpers must not leak PAT-in-URL either in argv or errors."""

    def test_strip_credentials_removes_userinfo(self) -> None:
        assert _strip_credentials("https://ghp_abc@github.com/o/r") == "https://github.com/o/r"
        assert _strip_credentials("https://user:pass@github.com/o/r") == "https://github.com/o/r"

    def test_strip_credentials_passes_through_bare_urls(self) -> None:
        assert _strip_credentials("https://github.com/o/r") == "https://github.com/o/r"

    def test_redact_scrubs_url_in_error_body(self) -> None:
        credentialed = "https://ghp_abc123@github.com/o/r"
        stderr = f"fatal: could not read from {credentialed}\nauthentication failed"
        redacted = _redact_url_in_text(stderr, credentialed)
        assert "ghp_abc123" not in redacted
        assert "authentication failed" in redacted

    def test_clone_repo_error_message_does_not_leak_pat(self, tmp_path: Path, monkeypatch) -> None:
        """A failing clone must not embed the PAT in the raised RuntimeError."""
        credentialed = "https://ghp_verysecret@github.com/does/not-exist"

        def fake_run(cmd, **kwargs):
            # Simulate git echoing the credentialed URL into stderr.
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=128,
                stdout="",
                stderr=f"fatal: repository '{credentialed}' not found\n",
            )

        with patch("dhub.core.git_repo.subprocess.run", side_effect=fake_run):
            with pytest.raises(RuntimeError) as excinfo:
                clone_repo(credentialed)
            # PAT must be gone from the surfaced error.
            assert "ghp_verysecret" not in str(excinfo.value)
            assert "git clone failed" in str(excinfo.value)

    def test_clone_repo_translates_timeout(self, monkeypatch) -> None:
        """A subprocess timeout is surfaced as a clean RuntimeError with no argv leak."""

        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=["git", "clone", "https://secret@github.com/o/r"], timeout=1)

        with patch("dhub.core.git_repo.subprocess.run", side_effect=raise_timeout):
            with pytest.raises(RuntimeError) as excinfo:
                clone_repo("https://secret@github.com/o/r")
            # The TimeoutExpired string form embeds the argv (including
            # the credentialed URL); our wrapper must not surface it.
            assert "secret" not in str(excinfo.value)
            assert "timed out" in str(excinfo.value)
