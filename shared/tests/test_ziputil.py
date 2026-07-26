"""Tests for dhub_core.ziputil — zip archive safety utilities."""

import io
import stat
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


def _make_symlink_zip(name: str, target: str) -> zipfile.ZipFile:
    """Create an in-memory zip with a POSIX symlink entry named *name* -> *target*."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo(name)
        # Encode a POSIX symlink in the external attributes.
        info.create_system = 3  # unix
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, target)
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

    def test_windows_separator_rejected(self) -> None:
        """Entries containing backslashes are rejected — a POSIX validator
        can't collapse them, but a Windows extractor would treat them as
        directory separators and let the entry escape."""
        zf = _make_zip({"..\\..\\evil.txt": b"malicious"})
        with pytest.raises(ValueError, match="invalid path separator"):
            validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_backslash_anywhere_rejected(self) -> None:
        """Even a benign-looking backslash inside a name is rejected —
        we can't reason about how downstream extractors will interpret it."""
        zf = _make_zip({"docs\\readme.md": b"content"})
        with pytest.raises(ValueError, match="invalid path separator"):
            validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_symlink_entry_rejected(self) -> None:
        """Zip entries encoding POSIX symlinks are rejected — the stdlib
        currently extracts them as regular files, but any change (or a
        third-party extractor honoring the mode) turns them into a
        path-escape vector via the symlink target."""
        zf = _make_symlink_zip("config", "/etc/shadow")
        with pytest.raises(ValueError, match="symlink"):
            validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_entry_count_cap_rejected(self) -> None:
        """Archives with more entries than the cap are rejected."""
        zf = _make_zip({f"file_{i}.txt": b"x" for i in range(50)})
        with pytest.raises(ValueError, match="too many entries"):
            validate_zip_entries(zf, "/tmp/target", max_entries=10)
        zf.close()

    def test_uncompressed_size_cap_rejected(self) -> None:
        """Archives whose total uncompressed size exceeds the cap are
        rejected — protects against zip bombs regardless of on-disk size."""
        zf = _make_zip({"big.bin": b"x" * 10_000})
        with pytest.raises(ValueError, match="uncompressed size"):
            validate_zip_entries(zf, "/tmp/target", max_uncompressed_bytes=1024)
        zf.close()

    def test_default_caps_allow_typical_skills(self) -> None:
        """A representative small skill archive fits well under the defaults."""
        zf = _make_zip(
            {
                "SKILL.md": b"# Skill" + b"a" * 5000,
                "scripts/run.py": b"print('hi')" * 100,
                "data/input.csv": b"col1,col2\n" + b"1,2\n" * 500,
            }
        )
        validate_zip_entries(zf, "/tmp/target")
        zf.close()
