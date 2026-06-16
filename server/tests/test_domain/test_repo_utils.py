"""Unit tests for decision_hub.domain.repo_utils — discover_skills, create_zip,
and _build_authenticated_url. clone_repo is exercised in integration suites
because it shells out to git."""

import io
import zipfile
from pathlib import Path

import pytest

from decision_hub.domain.repo_utils import (
    _build_authenticated_url,
    create_zip,
    discover_skills,
)

SKILL_MD = "---\nname: example\ndescription: A test skill\n---\nBody text\n"


def _write_skill(root: Path, *parts: str, name: str = "example", description: str = "A test skill") -> Path:
    """Materialize a minimal valid SKILL.md at root/parts/SKILL.md."""
    dest = root.joinpath(*parts)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\nBody\n")
    return dest


class TestDiscoverSkills:
    """discover_skills walks a directory and returns valid skill roots."""

    def test_finds_skill_at_root(self, tmp_path: Path) -> None:
        _write_skill(tmp_path)
        result = discover_skills(tmp_path)
        assert result == [tmp_path]

    def test_finds_nested_skill(self, tmp_path: Path) -> None:
        skill_dir = _write_skill(tmp_path, "skills", "my-skill")
        result = discover_skills(tmp_path)
        assert result == [skill_dir]

    def test_finds_multiple_distinct_skills(self, tmp_path: Path) -> None:
        a = _write_skill(tmp_path, "a", name="skill-a")
        b = _write_skill(tmp_path, "b", name="skill-b")
        result = sorted(discover_skills(tmp_path))
        assert result == sorted([a, b])

    def test_skips_hidden_directories(self, tmp_path: Path) -> None:
        """Skills inside dotfile directories (.git, .venv) must be ignored."""
        _write_skill(tmp_path, ".hidden")
        assert discover_skills(tmp_path) == []

    def test_skips_node_modules(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "node_modules", "x")
        assert discover_skills(tmp_path) == []

    def test_skips_pycache(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "__pycache__")
        assert discover_skills(tmp_path) == []

    def test_invalid_skill_md_is_skipped(self, tmp_path: Path) -> None:
        """A SKILL.md that fails to parse must not stop the walk."""
        broken = tmp_path / "broken"
        broken.mkdir()
        (broken / "SKILL.md").write_text("not valid frontmatter")

        good = _write_skill(tmp_path, "good")

        assert discover_skills(tmp_path) == [good]

    def test_shallowest_wins_on_name_collision(self, tmp_path: Path) -> None:
        """When two SKILL.md files declare the same skill name, only the
        shallowest one is returned. This prevents the same skill from being
        zipped twice with different checksums (per repo_utils docstring)."""
        shallow = _write_skill(tmp_path, "top", name="dup")
        _write_skill(tmp_path, "nested", "deeply", "dup", name="dup")
        assert discover_skills(tmp_path) == [shallow]


class TestCreateZip:
    """create_zip packages a skill directory into an in-memory archive."""

    def test_includes_skill_files(self, tmp_path: Path) -> None:
        (tmp_path / "SKILL.md").write_text(SKILL_MD)
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "run.py").write_text("print('hi')\n")

        data = create_zip(tmp_path)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = sorted(zf.namelist())
        assert names == ["SKILL.md", "scripts/run.py"]

    def test_excludes_hidden_files(self, tmp_path: Path) -> None:
        (tmp_path / "SKILL.md").write_text(SKILL_MD)
        (tmp_path / ".env").write_text("SECRET=value\n")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config").write_text("[core]\n")

        data = create_zip(tmp_path)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
        assert names == ["SKILL.md"]

    def test_excludes_pycache(self, tmp_path: Path) -> None:
        (tmp_path / "SKILL.md").write_text(SKILL_MD)
        cache = tmp_path / "scripts" / "__pycache__"
        cache.mkdir(parents=True)
        (cache / "run.cpython-311.pyc").write_bytes(b"\x00\x01")
        (tmp_path / "scripts" / "run.py").write_text("print('hi')\n")

        data = create_zip(tmp_path)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert sorted(zf.namelist()) == ["SKILL.md", "scripts/run.py"]

    def test_deterministic_ordering(self, tmp_path: Path) -> None:
        """Entries must appear in sorted order so the produced bytes are
        stable across runs — that stability feeds checksum-based dedup."""
        (tmp_path / "SKILL.md").write_text(SKILL_MD)
        (tmp_path / "z.txt").write_text("z\n")
        (tmp_path / "a.txt").write_text("a\n")

        data = create_zip(tmp_path)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert zf.namelist() == ["SKILL.md", "a.txt", "z.txt"]

    def test_empty_directory_produces_empty_archive(self, tmp_path: Path) -> None:
        data = create_zip(tmp_path)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert zf.namelist() == []


class TestBuildAuthenticatedUrl:
    """_build_authenticated_url rewrites HTTPS URLs to embed a token."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/pymc-labs/decision-hub",
            "https://github.com/pymc-labs/decision-hub.git",
        ],
    )
    def test_embeds_token_in_https_url(self, url: str) -> None:
        result = _build_authenticated_url(url, "ghs_abc123")
        assert result == "https://x-access-token:ghs_abc123@github.com/pymc-labs/decision-hub.git"
