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


class TestZipBombPrevention:
    """Tests for zip bomb prevention limits (Fix 7)."""

    def test_rejects_too_many_entries(self) -> None:
        """Zip with more entries than _MAX_ZIP_ENTRIES is rejected."""
        from decision_hub.domain.publish import _MAX_ZIP_ENTRIES

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: s\ndescription: d\n---\n")
            for i in range(_MAX_ZIP_ENTRIES + 1):
                zf.writestr(f"file_{i}.txt", "x")
        zip_bytes = buf.getvalue()

        with pytest.raises(ValueError, match="entries"):
            extract_for_evaluation(zip_bytes)

    def test_rejects_excessive_total_size(self) -> None:
        """Zip whose total uncompressed size exceeds _MAX_TOTAL_EXTRACTED is rejected."""
        from decision_hub.domain.publish import _MAX_FILE_SIZE, _MAX_TOTAL_EXTRACTED

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: s\ndescription: d\n---\n")
            # Create enough files to exceed total limit but stay under per-file limit
            num_files = (_MAX_TOTAL_EXTRACTED // _MAX_FILE_SIZE) + 2
            for i in range(num_files):
                zf.writestr(f"big_{i}.py", "x" * _MAX_FILE_SIZE)
        zip_bytes = buf.getvalue()

        with pytest.raises(ValueError, match="uncompressed size"):
            extract_for_evaluation(zip_bytes)

    def test_accepts_within_limits(self) -> None:
        """Zip within all limits is accepted."""
        zip_bytes = _make_zip(
            **{
                "SKILL.md": "---\nname: s\ndescription: d\n---\n",
                "main.py": "print('hello')",
            }
        )
        bundle = extract_for_evaluation(zip_bytes)
        assert "name: s" in bundle.skill_md_content
        assert len(bundle.source_files) == 1


class TestExtractForEvaluation:
    def test_rejects_oversized_file_in_zip(self) -> None:
        """A file whose uncompressed size exceeds the limit should raise ValueError."""
        from decision_hub.domain.publish import _MAX_FILE_SIZE

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: s\ndescription: d\n---\n")
            # Write a .py file that exceeds the per-file limit
            zf.writestr("huge.py", "x" * (_MAX_FILE_SIZE + 1))
        zip_bytes = buf.getvalue()

        with pytest.raises(ValueError, match="exceeds maximum size"):
            extract_for_evaluation(zip_bytes)

    def test_extracts_skill_md_and_python_files(self) -> None:
        zip_bytes = _make_zip(
            **{
                "SKILL.md": "---\nname: test\ndescription: test\n---\nbody",
                "main.py": "print('hello')",
                "lib/utils.py": "def helper(): pass",
            }
        )
        bundle = extract_for_evaluation(zip_bytes)

        assert "name: test" in bundle.skill_md_content
        assert len(bundle.source_files) == 2
        filenames = [name for name, _ in bundle.source_files]
        assert "main.py" in filenames
        assert "lib/utils.py" in filenames
        assert bundle.lockfile_content is None

    def test_extracts_lockfile(self) -> None:
        zip_bytes = _make_zip(
            **{
                "SKILL.md": "---\nname: s\ndescription: d\n---\n",
                "requirements.txt": "requests==2.31.0\n",
            }
        )
        bundle = extract_for_evaluation(zip_bytes)
        assert bundle.lockfile_content is not None
        assert "requests" in bundle.lockfile_content

    def test_raises_on_missing_skill_md(self) -> None:
        zip_bytes = _make_zip(**{"main.py": "pass"})
        with pytest.raises(ValueError, match=r"SKILL\.md"):
            extract_for_evaluation(zip_bytes)

    def test_nested_skill_md(self) -> None:
        """SKILL.md in a subdirectory should still be found."""
        zip_bytes = _make_zip(**{"subdir/SKILL.md": "---\nname: nested\ndescription: d\n---\n"})
        bundle = extract_for_evaluation(zip_bytes)
        assert "name: nested" in bundle.skill_md_content
        assert bundle.source_files == []
        assert bundle.lockfile_content is None

    def test_skips_directories(self) -> None:
        """Zip entries ending with / (directories) should be skipped."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: s\ndescription: d\n---\n")
            zf.writestr("subdir/", "")  # directory entry
        zip_bytes = buf.getvalue()
        bundle = extract_for_evaluation(zip_bytes)
        assert bundle.skill_md_content
        assert bundle.source_files == []

    def test_uv_lock_as_lockfile(self) -> None:
        zip_bytes = _make_zip(
            **{
                "SKILL.md": "---\nname: s\ndescription: d\n---\n",
                "uv.lock": "some-lock-content",
            }
        )
        bundle = extract_for_evaluation(zip_bytes)
        assert bundle.lockfile_content == "some-lock-content"

    def test_zip_entries_populated(self) -> None:
        """zip_entries should contain metadata for all non-directory entries."""
        zip_bytes = _make_zip(
            **{
                "SKILL.md": "---\nname: s\ndescription: d\n---\n",
                "main.py": "print('hello')",
                "config.json": "{}",
            }
        )
        bundle = extract_for_evaluation(zip_bytes)
        assert len(bundle.zip_entries) == 3
        names = [name for name, _, _ in bundle.zip_entries]
        assert "SKILL.md" in names
        assert "main.py" in names
        assert "config.json" in names
        # Check extensions
        exts = {ext for _, _, ext in bundle.zip_entries}
        assert ".md" in exts
        assert ".py" in exts
        assert ".json" in exts
