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


class TestSymlinkRejection:
    """Symlink entries are refused outright — see ziputil docstring."""

    @staticmethod
    def _zip_with_symlink_entry(name: str, target: bytes) -> zipfile.ZipFile:
        """Build a zip containing a UNIX-mode symlink entry."""
        import stat

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo(name)
            info.create_system = 3  # UNIX
            # Symlink mode (0o120000) + permission bits in the upper half
            # of external_attr — same encoding Info-ZIP uses.
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
        buf.seek(0)
        return zipfile.ZipFile(buf, "r")

    def test_symlink_entry_pointing_outside_target_is_rejected(self) -> None:
        zf = self._zip_with_symlink_entry("evil-link", b"/etc/passwd")
        with pytest.raises(ValueError, match="symlink"):
            validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_symlink_entry_with_relative_target_is_also_rejected(self) -> None:
        """We reject all symlink entries, not just ones pointing outside."""
        zf = self._zip_with_symlink_entry("link", b"./safe.txt")
        with pytest.raises(ValueError, match="symlink"):
            validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_regular_file_with_unix_mode_is_allowed(self) -> None:
        """Plain regular files set their own mode bits; that's fine."""
        import stat

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            info = zipfile.ZipInfo("script.sh")
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o755) << 16
            zf.writestr(info, b"#!/bin/sh\necho hi\n")
        buf.seek(0)
        zf = zipfile.ZipFile(buf, "r")
        validate_zip_entries(zf, "/tmp/target")  # should not raise
        zf.close()
