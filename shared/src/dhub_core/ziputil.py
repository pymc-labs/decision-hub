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

    Args:
        zf: An open ZipFile to validate.
        target_dir: The directory entries will be extracted into.

    Raises:
        ValueError: If any entry resolves outside target_dir.
    """
    safe_prefix = os.path.normpath(target_dir) + os.sep

    for info in zf.infolist():
        resolved = os.path.normpath(os.path.join(target_dir, info.filename))
        # Allow the target dir itself (for directory entries named ".")
        if resolved != os.path.normpath(target_dir) and not resolved.startswith(safe_prefix):
            raise ValueError(f"Zip entry escapes target directory: {info.filename!r}")
