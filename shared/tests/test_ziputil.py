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


def _make_zip_with_mode(filename: str, content: bytes, unix_mode: int) -> zipfile.ZipFile:
    """Create an in-memory ZipFile where ``filename`` has the given Unix mode."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo(filename)
        info.create_system = 3  # Unix
        info.external_attr = unix_mode << 16
        zf.writestr(info, content)
    buf.seek(0)
    return zipfile.ZipFile(buf, "r")


class TestSpecialFileTypes:
    """validate_zip_entries rejects symlinks and other non-regular files."""

    def test_symlink_entry_rejected(self) -> None:
        """A symlink entry (S_IFLNK | 0o777) must be rejected even when the
        filename itself resolves inside the target directory. Without this
        guard, an extractor that honors symlinks (e.g. system ``unzip``)
        could materialize the link and let subsequent writes escape."""
        # 0o120777 == S_IFLNK | rwxrwxrwx
        zf = _make_zip_with_mode("link", b"../../etc/passwd", 0o120777)
        with pytest.raises(ValueError, match="unsupported file type"):
            validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_device_node_entry_rejected(self) -> None:
        """Character/block device entries must be rejected."""
        # 0o020666 == S_IFCHR | rw-rw-rw-
        zf = _make_zip_with_mode("dev_null", b"", 0o020666)
        with pytest.raises(ValueError, match="unsupported file type"):
            validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_regular_file_with_explicit_mode_allowed(self) -> None:
        """A regular file with a Unix mode set must still be accepted."""
        # 0o100644 == S_IFREG | rw-r--r--
        zf = _make_zip_with_mode("README.md", b"hi", 0o100644)
        validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_directory_entry_with_unix_mode_allowed(self) -> None:
        """A directory entry with an explicit Unix mode must be accepted."""
        # 0o040755 == S_IFDIR | rwxr-xr-x
        zf = _make_zip_with_mode("subdir/", b"", 0o040755)
        validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_non_unix_create_system_not_treated_as_symlink(self) -> None:
        """When create_system != 3 (e.g. Windows), the external_attr bits
        aren't Unix mode bits and must not be misinterpreted as a symlink."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("normal.txt")
            info.create_system = 0  # MS-DOS / Windows
            # Bits that would look like S_IFLNK if read as Unix mode
            info.external_attr = 0o120000 << 16
            zf.writestr(info, b"content")
        buf.seek(0)
        zf = zipfile.ZipFile(buf, "r")
        validate_zip_entries(zf, "/tmp/target")
        zf.close()
