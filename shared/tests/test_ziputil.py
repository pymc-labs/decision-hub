"""Tests for dhub_core.ziputil — zip archive safety utilities."""

import io
import stat
import zipfile

import pytest

from dhub_core.ziputil import validate_zip_entries, validate_zip_safety


def _make_zip(entries: dict[str, bytes]) -> zipfile.ZipFile:
    """Create an in-memory ZipFile with the given filename -> content mapping."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    buf.seek(0)
    return zipfile.ZipFile(buf, "r")


def _make_symlink_zip(link_name: str, link_target: str) -> zipfile.ZipFile:
    """Create an in-memory ZipFile containing a Unix symlink entry.

    The symlink is encoded the same way ``zip -y`` does it: file-type
    bits ``S_IFLNK`` packed into the high half-word of ``external_attr``
    with the link target as the entry payload.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo(link_name)
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zf.writestr(info, link_target)
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
        """A symlink entry is refused even when its name resolves inside target."""
        zf = _make_symlink_zip("link.txt", "/etc/passwd")
        with pytest.raises(ValueError, match="symlink"):
            validate_zip_entries(zf, "/tmp/target")
        zf.close()

    def test_max_entries_enforced(self) -> None:
        """An archive with more entries than max_entries is rejected."""
        zf = _make_zip({f"file{i}.txt": b"x" for i in range(5)})
        with pytest.raises(ValueError, match="exceeding limit of 3"):
            validate_zip_entries(zf, "/tmp/target", max_entries=3)
        zf.close()

    def test_max_total_size_enforced(self) -> None:
        """An archive whose total uncompressed size exceeds the cap is rejected."""
        zf = _make_zip({"big.txt": b"x" * (2 * 1024 * 1024)})
        with pytest.raises(ValueError, match="exceeds limit"):
            validate_zip_entries(zf, "/tmp/target", max_total_size=1024 * 1024)
        zf.close()


class TestValidateZipSafety:
    """validate_zip_safety covers symlinks and caps without a target dir."""

    def test_clean_archive_passes(self) -> None:
        """A normal archive within caps passes without raising."""
        zf = _make_zip({"SKILL.md": b"# Skill", "run.py": b"print('hi')"})
        validate_zip_safety(zf, max_entries=10, max_total_size=1024 * 1024)
        zf.close()

    def test_symlink_rejected(self) -> None:
        """A symlink entry is rejected at the safety layer too."""
        zf = _make_symlink_zip("link.txt", "/etc/passwd")
        with pytest.raises(ValueError, match="symlink"):
            validate_zip_safety(zf)
        zf.close()

    def test_no_caps_passes(self) -> None:
        """With no caps specified, only the symlink check runs."""
        zf = _make_zip({f"file{i}.txt": b"x" * 1024 for i in range(50)})
        validate_zip_safety(zf)
        zf.close()
