"""Zip archive safety utilities.

Provides path-traversal validation for zip extraction to prevent
zip-slip attacks where malicious entries escape the target directory.
"""

import os
import zipfile


def validate_zip_entries(zf: zipfile.ZipFile, target_dir: str) -> None:
    """Validate that no zip entries escape the target directory.

    Checks every entry in the archive to ensure its resolved path
    stays within *target_dir*.  This prevents zip-slip attacks where
    entries like ``../../.bashrc`` write outside the intended location.

    Uses ``os.path.realpath`` (not just ``normpath``) on both target
    and resolved entry paths so symlinks in the target directory are
    followed before the prefix check.  ``normpath`` only collapses
    ``..`` lexically, which lets a symlinked subdir escape on extraction
    even though the textual path looks safe.

    Args:
        zf: An open ZipFile to validate.
        target_dir: The directory entries will be extracted into.

    Raises:
        ValueError: If any entry resolves outside target_dir.
    """
    safe_root = os.path.realpath(target_dir)
    safe_prefix = safe_root + os.sep

    for info in zf.infolist():
        resolved = os.path.realpath(os.path.join(target_dir, info.filename))
        # Allow the target dir itself (for directory entries named ".")
        if resolved != safe_root and not resolved.startswith(safe_prefix):
            raise ValueError(f"Zip entry escapes target directory: {info.filename!r}")
