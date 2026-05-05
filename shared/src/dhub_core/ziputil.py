"""Zip archive safety utilities.

Provides path-traversal validation for zip extraction to prevent
zip-slip attacks where malicious entries escape the target directory.
"""

import os
import stat
import zipfile

# Unix file-type bits live in the upper 16 bits of ZipInfo.external_attr.
# A symlink has mode S_IFLNK (0o120000); we shift the attr down by 16 to
# extract the regular ``stat`` mode bits.
_SYMLINK_MODE = 0o120000


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """Return True if a zip entry was archived as a Unix symlink.

    Python's ``zipfile`` does not expose a high-level ``is_symlink``
    helper, but the Unix file type lives in the top 16 bits of
    ``external_attr``. Windows-created archives leave this zero, so the
    check is a no-op on those.
    """
    return stat.S_IFMT(info.external_attr >> 16) == _SYMLINK_MODE


def validate_zip_entries(zf: zipfile.ZipFile, target_dir: str) -> None:
    """Validate that no zip entries escape the target directory.

    Two attack classes are blocked:

    1. **Path traversal** — entries whose resolved path falls outside
       *target_dir* (e.g. ``../../.bashrc``, absolute paths,
       ``a/../../b``).
    2. **Symlink slip** — entries archived as Unix symlinks. Even when
       the symlink's *name* is safe, the *target* it points to is read
       only at use-time, so a symlink like ``data.json -> /etc/passwd``
       would expose host files when later code does
       ``open(skill_dir / "data.json")``. We don't try to validate
       individual targets — we reject all symlinks because the skill
       format has no legitimate use for them.

    Args:
        zf: An open ZipFile to validate.
        target_dir: The directory entries will be extracted into.

    Raises:
        ValueError: If any entry escapes target_dir or is a symlink.
    """
    safe_prefix = os.path.normpath(target_dir) + os.sep

    for info in zf.infolist():
        if _is_symlink(info):
            raise ValueError(f"Zip entry is a symlink (not allowed): {info.filename!r}")

        resolved = os.path.normpath(os.path.join(target_dir, info.filename))
        # Allow the target dir itself (for directory entries named ".")
        if resolved != os.path.normpath(target_dir) and not resolved.startswith(safe_prefix):
            raise ValueError(f"Zip entry escapes target directory: {info.filename!r}")
