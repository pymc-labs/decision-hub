"""Zip archive safety utilities.

Provides path-traversal validation for zip extraction to prevent
zip-slip attacks where malicious entries escape the target directory
or use symlinks to read files outside it.
"""

import os
import stat
import zipfile

# Unix file-type bits live in the upper 16 of external_attr; mask isolates
# the file-type nibble so we can identify symlink entries (0o120000).
_UNIX_FILE_TYPE_MASK = 0o170000


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """Return True if *info* represents a symbolic link entry."""
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode & _UNIX_FILE_TYPE_MASK)


def validate_zip_entries(zf: zipfile.ZipFile, target_dir: str) -> None:
    """Validate that no zip entries escape the target directory.

    Checks every entry in the archive to ensure (a) its resolved path
    stays within *target_dir* and (b) it is not a symbolic link.
    Symlinks are rejected outright because, even when their *entry name*
    stays inside the target, the link target can point anywhere on the
    host filesystem and would be silently followed by later reads.

    Args:
        zf: An open ZipFile to validate.
        target_dir: The directory entries will be extracted into.

    Raises:
        ValueError: If any entry is a symlink or resolves outside target_dir.
    """
    safe_prefix = os.path.normpath(target_dir) + os.sep
    normalized_target = os.path.normpath(target_dir)

    for info in zf.infolist():
        if _is_symlink(info):
            raise ValueError(f"Zip entry is a symbolic link, which is not allowed: {info.filename!r}")
        resolved = os.path.normpath(os.path.join(target_dir, info.filename))
        # Allow the target dir itself (for directory entries named ".")
        if resolved != normalized_target and not resolved.startswith(safe_prefix):
            raise ValueError(f"Zip entry escapes target directory: {info.filename!r}")
