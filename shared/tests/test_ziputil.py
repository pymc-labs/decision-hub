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
        """A zip entry encoded as a Unix symlink should be rejected.

        Even though the entry *name* may stay inside target_dir, the symlink
        target can point anywhere on the host filesystem and would be silently
        followed when later code reads the extracted file.
        """
        import stat as _stat

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("inside/link.txt")
            # 0o120000 marks the entry as a symlink in the Unix mode bits;
            # bits live in the upper 16 of external_attr per the zip spec.
            info.create_system = 3  # Unix
            info.external_attr = (_stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, b"/etc/passwd")
        buf.seek(0)
        zf = zipfile.ZipFile(buf, "r")
        with pytest.raises(ValueError, match="symbolic link"):
            validate_zip_entries(zf, "/tmp/target")
        zf.close()
