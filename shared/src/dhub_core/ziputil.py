"""Zip archive safety utilities.

Provides path-traversal and symlink validation for zip extraction. Both
classes of attack let a malicious archive write or reference files outside
the intended target directory; both have to be checked before
``ZipFile.extractall``, not after.
"""

import os
import stat
import zipfile

# Unix file-type bits live in the upper half of ``external_attr`` for entries
# created by Info-ZIP/zipfile on POSIX. ``S_IFLNK`` => symbolic link.
_UNIX_SYMLINK_MODE = stat.S_IFLNK


def _is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    """Return True if *info* is encoded as a symlink.

    Python's stdlib ``zipfile`` does not expose ``is_symlink``, so we read
    the Unix permission bits out of ``external_attr`` directly. Archives
    created on platforms that don't encode symlinks (DOS/Windows) return
    a zero attr and fail this check, which is what we want.
    """
    if info.create_system != 3:  # 3 = UNIX
        return False
    mode = (info.external_attr >> 16) & 0xFFFF
    return (mode & 0xF000) == _UNIX_SYMLINK_MODE


def validate_zip_entries(zf: zipfile.ZipFile, target_dir: str) -> None:
    """Validate that the archive is safe to extract into *target_dir*.

    Two checks:

    1. No entry escapes *target_dir* via ``..`` or absolute paths
       (classic zip-slip).
    2. No entry is encoded as a symlink. Even though Python's
       ``ZipFile.extractall`` writes symlink entries as regular files
       containing the target path (so the link itself is benign), tools
       downstream of us — git tooling, archive viewers, ``zip`` from
       Info-ZIP — *will* materialise real symlinks and can then be made
       to read or write outside the sandbox. Rejecting them up front is
       cheap and removes an entire class of pitfalls.

    Args:
        zf: An open ZipFile to validate.
        target_dir: The directory entries will be extracted into.

    Raises:
        ValueError: If any entry resolves outside target_dir or is a
            symlink.
    """
    safe_prefix = os.path.normpath(target_dir) + os.sep

    for info in zf.infolist():
        if _is_symlink_entry(info):
            raise ValueError(f"Zip entry is a symlink, refusing to extract: {info.filename!r}")
        resolved = os.path.normpath(os.path.join(target_dir, info.filename))
        # Allow the target dir itself (for directory entries named ".")
        if resolved != os.path.normpath(target_dir) and not resolved.startswith(safe_prefix):
            raise ValueError(f"Zip entry escapes target directory: {info.filename!r}")
