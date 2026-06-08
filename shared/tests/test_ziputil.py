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

    def test_rejects_entry_escaping_via_symlinked_target(self, tmp_path) -> None:
        """Symlinked target dirs must not provide a bypass.

        With ``normpath`` alone, ``target_dir/escape/x.txt`` could resolve
        to ``/tmp/.../target/escape/x.txt`` lexically — looking safe —
        even when ``target/escape`` is a symlink pointing outside the
        sandbox. ``realpath`` follows the symlink so the real on-disk
        path is checked.
        """
        outside = tmp_path / "outside"
        outside.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        # ``escape`` lives inside the target dir lexically but resolves
        # to ``outside`` on disk.
        (target / "escape").symlink_to(outside, target_is_directory=True)

        zf = _make_zip({"escape/poisoned.txt": b"x"})
        with pytest.raises(ValueError, match="escapes target directory"):
            validate_zip_entries(zf, str(target))
        zf.close()

    def test_accepts_safe_entry_when_target_itself_is_symlink(self, tmp_path) -> None:
        """A symlinked target is fine as long as entries stay under it."""
        real = tmp_path / "real-target"
        real.mkdir()
        linked = tmp_path / "linked-target"
        linked.symlink_to(real, target_is_directory=True)

        zf = _make_zip({"SKILL.md": b"# Skill"})
        validate_zip_entries(zf, str(linked))  # must not raise
        zf.close()
