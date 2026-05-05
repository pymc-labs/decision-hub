"""Tests for dhub_core.ziputil — zip archive safety utilities."""

import io
import zipfile

import pytest

from dhub_core.ziputil import validate_zip_entries


def _make_zip(entries: dict[str, bytes]) -> zipfile.ZipFile:
    """Create an in-memory ZipFile with the given filename -> content mapping."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf, "r")


class TestValidateZipEntries:
    """validate_zip_entries blocks path-traversal and allows safe entries."""

    def test_safe_entries_pass(self) -> None:
        """Normal entries within the target directory should pass."""
        zf = _make_zip(
            {
                "SKILL.md": b"# Skill",
                "scripts/run.py": b"print('hi')",
                "data/input.csv": b"a,b,c",
            }
        )
        # Should not raise
        validate_zip_entries(zf, "/home/sandbox/skills/org/my-skill")
        zf.close()

    def test_parent_traversal_rejected(self) -> None:
        """An entry with ../../ should be rejected."""
        zf = _make_zip({"../../.bashrc": b"malicious"})
        with pytest.raises(ValueError, match="escapes target directory"):
            validate_zip_entries(zf, "/home/sandbox/skills/org/my-skill")
        zf.close()

    def test_absolute_path_rejected(self) -> None:
        """An entry with an absolute path should be rejected."""
        zf = _make_zip({"/etc/passwd": b"root:x:0:0"})
        with pytest.raises(ValueError, match="escapes target directory"):
            validate_zip_entries(zf, "/home/sandbox/skills/org/my-skill")
        zf.close()

    def test_dot_dot_in_middle_rejected(self) -> None:
        """Entries like 'subdir/../../.bashrc' that escape should be rejected."""
        zf = _make_zip({"subdir/../../.bashrc": b"malicious"})
        with pytest.raises(ValueError, match="escapes target directory"):
            validate_zip_entries(zf, "/home/sandbox/skills/org/my-skill")
        zf.close()

    def test_dot_dot_that_stays_inside_allowed(self) -> None:
        """An entry like 'a/b/../c.txt' that resolves inside target is fine."""
        zf = _make_zip({"a/b/../c.txt": b"safe"})
        # Resolves to <target>/a/c.txt — still inside target
        validate_zip_entries(zf, "/home/sandbox/skills/org/my-skill")
        zf.close()

    def test_empty_zip_passes(self) -> None:
        """An empty zip should pass without errors."""
        zf = _make_zip({})
        validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_directory_entries_pass(self) -> None:
        """Directory entries (trailing slash) should pass when safe."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            # Add a directory entry
            zf.mkdir("subdir/")
            zf.writestr("subdir/file.txt", b"content")
        buf.seek(0)
        zf = zipfile.ZipFile(buf, "r")
        validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_sibling_escape_via_prefix_rejected(self) -> None:
        """An entry that shares a prefix but escapes (e.g. ../target2/x)."""
        zf = _make_zip({"../target2/evil.txt": b"malicious"})
        with pytest.raises(ValueError, match="escapes target directory"):
            validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_symlink_entry_rejected(self) -> None:
        """A zip entry archived as a Unix symlink must be rejected.

        The entry's *name* (``data.json``) sits safely inside target_dir,
        but the symlink target (``/etc/passwd``) would be followed at
        use-time, exposing host files. Skill packages have no legitimate
        use for symlinks, so we reject them outright.
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("data.json")
            # Top 16 bits of external_attr are the Unix mode; 0o120000 = symlink
            info.external_attr = (0o120777 & 0xFFFF) << 16
            info.create_system = 3  # Unix
            zf.writestr(info, "/etc/passwd")
        buf.seek(0)
        zf = zipfile.ZipFile(buf, "r")
        with pytest.raises(ValueError, match="symlink"):
            validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_symlink_with_traversing_name_rejected(self) -> None:
        """A symlink with a traversing name should still be rejected (as symlink)."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("../escape")
            info.external_attr = (0o120777 & 0xFFFF) << 16
            info.create_system = 3
            zf.writestr(info, "/etc/shadow")
        buf.seek(0)
        zf = zipfile.ZipFile(buf, "r")
        # Either rejection reason is acceptable — the call must raise.
        with pytest.raises(ValueError):
            validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_windows_archive_no_symlink_metadata_passes(self) -> None:
        """Archives created on Windows leave external_attr's mode bits zero.

        Such entries must not be misclassified as symlinks (a regression
        here would break every Windows-published skill).
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("SKILL.md")
            info.external_attr = 0  # Windows leaves mode bits zero
            info.create_system = 0  # FAT/Windows
            zf.writestr(info, "# Skill")
        buf.seek(0)
        zf = zipfile.ZipFile(buf, "r")
        validate_zip_entries(zf, "/tmp/target")  # should not raise
        zf.close()
