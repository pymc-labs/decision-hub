"""Zip archive safety utilities.

Provides path-traversal validation for zip extraction to prevent
zip-slip and zip-bomb attacks:

* Directory-traversal entries (``../``) and absolute paths are rejected.
* Windows-style backslash separators are rejected — POSIX ``normpath``
  treats them as literal characters, so a validator running on Linux
  can miss escapes that trigger when the same archive is extracted on
  Windows.
* Symlink entries are rejected: their unix mode bits are ``0o120000``.
  The standard library currently extracts them as regular files, but
  any third-party extractor (or a future stdlib change) that honors
  the mode turns them into a path-escape vector.
* Total uncompressed size and entry count are capped to bound
  zip-bomb amplification.
"""

import os
import stat
import zipfile

# ~200 MB uncompressed, ~2000 entries — comfortably above any real skill
# archive we've seen while keeping runaway extraction bounded.
_DEFAULT_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
_DEFAULT_MAX_ENTRIES = 2000

_SYMLINK_MODE = 0o120000  # stat.S_IFLNK, encoded in ZipInfo.external_attr


def _is_symlink_entry(info: zipfile.ZipInfo) -> bool:
    """Return True if the zip entry encodes a POSIX symlink."""
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode) or (mode & 0o170000) == _SYMLINK_MODE


def validate_zip_entries(
    zf: zipfile.ZipFile,
    target_dir: str,
    *,
    max_entries: int = _DEFAULT_MAX_ENTRIES,
    max_uncompressed_bytes: int = _DEFAULT_MAX_UNCOMPRESSED_BYTES,
) -> None:
    """Validate that a zip archive is safe to extract into *target_dir*.

    Rejects zip-slip (``../`` escapes, absolute paths, and Windows-style
    ``..\\`` escapes that would only trigger on Windows extractors),
    symlink entries, and archives that exceed size / entry-count caps.

    Args:
        zf: An open ZipFile to validate.
        target_dir: The directory entries will be extracted into.
        max_entries: Reject archives with more than this many entries.
        max_uncompressed_bytes: Reject archives whose total uncompressed
            size exceeds this many bytes.

    Raises:
        ValueError: If any entry escapes the target directory, encodes a
            symlink, or if the archive exceeds the configured caps.
    """
    infos = zf.infolist()
    if len(infos) > max_entries:
        raise ValueError(f"Zip archive has too many entries ({len(infos)} > {max_entries})")

    total_size = 0
    safe_target = os.path.normpath(target_dir)
    safe_prefix = safe_target + os.sep

    for info in infos:
        name = info.filename
        # Reject Windows-style separators outright. On POSIX ``normpath``
        # doesn't collapse them, so ``..\\..\\evil`` would pass the prefix
        # check here but escape when extracted on Windows.
        if "\\" in name:
            raise ValueError(f"Zip entry uses invalid path separator: {name!r}")
        if _is_symlink_entry(info):
            raise ValueError(f"Zip entry is a symlink: {name!r}")

        total_size += info.file_size
        if total_size > max_uncompressed_bytes:
            raise ValueError(
                f"Zip archive uncompressed size exceeds cap ({total_size} > {max_uncompressed_bytes} bytes)"
            )

        resolved = os.path.normpath(os.path.join(target_dir, name))
        # Allow the target dir itself (for directory entries named ".")
        if resolved != safe_target and not resolved.startswith(safe_prefix):
            raise ValueError(f"Zip entry escapes target directory: {name!r}")
