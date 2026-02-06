"""Tests for decision_hub.domain.publish -- semver, S3 key, skill name validation, and zip extraction."""

import io
import zipfile

import pytest

from decision_hub.domain.publish import (
    build_s3_key,
    extract_for_evaluation,
    validate_semver,
    validate_skill_name,
)


# ---------------------------------------------------------------------------
# validate_semver
# ---------------------------------------------------------------------------

class TestValidateSemver:

    @pytest.mark.parametrize(
        "version",
        [
            "0.0.1",
            "1.0.0",
            "10.20.30",
            "0.0.0",
            "999.999.999",
        ],
    )
    def test_valid_semver(self, version: str) -> None:
        assert validate_semver(version) == version

    @pytest.mark.parametrize(
        "version,reason",
        [
            ("1.0", "only two parts"),
            ("01.0.0", "leading zero in major"),
            ("0.01.0", "leading zero in minor"),
            ("0.0.01", "leading zero in patch"),
            ("v1.0.0", "v prefix not allowed"),
            ("", "empty string"),
            ("1.0.0-beta", "pre-release suffix not allowed"),
            ("1.0.0.0", "four parts"),
            ("abc", "non-numeric"),
        ],
    )
    def test_invalid_semver(self, version: str, reason: str) -> None:
        with pytest.raises(ValueError):
            validate_semver(version)


# ---------------------------------------------------------------------------
# build_s3_key
# ---------------------------------------------------------------------------

class TestBuildS3Key:

    def test_format(self) -> None:
        key = build_s3_key("my-org", "my-skill", "1.2.3")
        assert key == "skills/my-org/my-skill/1.2.3.zip"

    def test_different_inputs(self) -> None:
        key = build_s3_key("acme", "parser", "0.0.1")
        assert key == "skills/acme/parser/0.0.1.zip"


# ---------------------------------------------------------------------------
# validate_skill_name
# ---------------------------------------------------------------------------

class TestValidateSkillName:

    @pytest.mark.parametrize(
        "name",
        [
            "a",
            "my-skill",
            "skill123",
            "a" * 64,
            "code-review",
        ],
    )
    def test_valid_names(self, name: str) -> None:
        assert validate_skill_name(name) == name

    @pytest.mark.parametrize(
        "name,reason",
        [
            ("", "empty string"),
            ("a" * 65, "too long"),
            ("-leading-hyphen", "leading hyphen"),
            ("trailing-hyphen-", "trailing hyphen"),
            ("UpperCase", "uppercase not allowed"),
            ("has space", "spaces not allowed"),
            ("under_score", "underscores not allowed"),
        ],
    )
    def test_invalid_names(self, name: str, reason: str) -> None:
        with pytest.raises(ValueError):
            validate_skill_name(name)


# ---------------------------------------------------------------------------
# extract_for_evaluation
# ---------------------------------------------------------------------------


def _make_zip(**files: str) -> bytes:
    """Create an in-memory zip with the given filename -> content pairs."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


class TestExtractForEvaluation:

    def test_extracts_skill_md_and_python_files(self) -> None:
        zip_bytes = _make_zip(
            **{
                "SKILL.md": "---\nname: test\ndescription: test\n---\nbody",
                "main.py": "print('hello')",
                "lib/utils.py": "def helper(): pass",
            }
        )
        skill_md, sources, lockfile = extract_for_evaluation(zip_bytes)

        assert "name: test" in skill_md
        assert len(sources) == 2
        filenames = [name for name, _ in sources]
        assert "main.py" in filenames
        assert "lib/utils.py" in filenames
        assert lockfile is None

    def test_extracts_lockfile(self) -> None:
        zip_bytes = _make_zip(
            **{
                "SKILL.md": "---\nname: s\ndescription: d\n---\n",
                "requirements.txt": "requests==2.31.0\n",
            }
        )
        _, _, lockfile = extract_for_evaluation(zip_bytes)
        assert lockfile is not None
        assert "requests" in lockfile

    def test_raises_on_missing_skill_md(self) -> None:
        zip_bytes = _make_zip(**{"main.py": "pass"})
        with pytest.raises(ValueError, match="SKILL.md"):
            extract_for_evaluation(zip_bytes)

    def test_nested_skill_md(self) -> None:
        """SKILL.md in a subdirectory should still be found."""
        zip_bytes = _make_zip(
            **{"subdir/SKILL.md": "---\nname: nested\ndescription: d\n---\n"}
        )
        skill_md, sources, lockfile = extract_for_evaluation(zip_bytes)
        assert "name: nested" in skill_md
        assert sources == []
        assert lockfile is None

    def test_skips_directories(self) -> None:
        """Zip entries ending with / (directories) should be skipped."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: s\ndescription: d\n---\n")
            zf.writestr("subdir/", "")  # directory entry
        zip_bytes = buf.getvalue()
        skill_md, sources, lockfile = extract_for_evaluation(zip_bytes)
        assert skill_md
        assert sources == []

    def test_uv_lock_as_lockfile(self) -> None:
        zip_bytes = _make_zip(
            **{
                "SKILL.md": "---\nname: s\ndescription: d\n---\n",
                "uv.lock": "some-lock-content",
            }
        )
        _, _, lockfile = extract_for_evaluation(zip_bytes)
        assert lockfile == "some-lock-content"
