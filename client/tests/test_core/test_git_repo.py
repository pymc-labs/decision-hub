"""Tests for dhub.core.git_repo -- clone and skill discovery."""

import contextlib
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


class TestCloneRepo:
    """Ensure clone_repo builds subprocess args that resist injection and hangs."""

    def _fake_run(self, *args, **kwargs) -> MagicMock:
        return MagicMock(returncode=0, stderr="")

    def test_uses_double_dash_separator_for_default_clone(self) -> None:
        # A repo URL that starts with `-` would previously be interpreted by
        # git as an option (e.g. `--upload-pack=<attacker binary>`) and let
        # a hostile publish invocation execute arbitrary code. The `--`
        # separator forces git to treat the remainder as positional args.
        with (
            patch("dhub.core.git_repo.subprocess.run", side_effect=self._fake_run) as run,
            contextlib.suppress(Exception),
        ):
            clone_repo("--upload-pack=pwn https://x")
        cmd = run.call_args_list[0].args[0]
        assert "--" in cmd
        assert cmd.index("--") < cmd.index("--upload-pack=pwn https://x")

    def test_uses_double_dash_separator_for_sha_clone(self) -> None:
        with (
            patch("dhub.core.git_repo.subprocess.run", side_effect=self._fake_run) as run,
            contextlib.suppress(Exception),
        ):
            clone_repo("https://github.com/o/r.git", ref="deadbeef1234567")
        # First call is `git clone`, second is `git checkout`. Both must
        # include `--` before user-controlled arguments.
        assert "--" in run.call_args_list[0].args[0]
        assert "--" in run.call_args_list[1].args[0]

    def test_passes_timeout(self) -> None:
        with (
            patch("dhub.core.git_repo.subprocess.run", side_effect=self._fake_run) as run,
            contextlib.suppress(Exception),
        ):
            clone_repo("https://github.com/o/r.git")
        assert run.call_args_list[0].kwargs.get("timeout")

    def test_timeout_expired_becomes_runtime_error(self) -> None:
        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="git", timeout=1)

        with (
            patch("dhub.core.git_repo.subprocess.run", side_effect=raise_timeout),
            pytest.raises(RuntimeError, match="timed out"),
        ):
            clone_repo("https://github.com/o/r.git")
