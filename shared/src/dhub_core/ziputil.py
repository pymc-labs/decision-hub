"""Zip archive safety utilities.

Provides defensive checks for untrusted zip archives:

* :func:`validate_zip_safety` — symlink rejection, entry-count cap, and
  total-uncompressed-size cap.  Use this when extracting *in memory*
  (no destination directory).
* :func:`validate_zip_entries` — everything from ``validate_zip_safety``
  plus path-traversal protection relative to a destination directory.
  Use this before any on-disk extraction (zip-slip prevention).

All checks raise :class:`ValueError` on the first violation so callers
get a clear error and never iterate further into a malicious archive.
"""

import os
import stat
import zipfile

# Upper four bits of the high half-word of ``external_attr`` encode the
# Unix file-type bits (see PKZIP APPNOTE.TXT and ``stat(2)``).  We use
# this to detect symlinks regardless of the zip tool that produced them.
_UNIX_TYPE_MASK = 0o170000


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """Return True if the zip entry is a Unix symlink.

    ``zipfile.ZipInfo`` does not expose ``is_symlink()`` directly, so we
    inspect the upper bits of ``external_attr`` for ``S_IFLNK``.  Any
    archive entry produced on Unix carries its file-type bits there.
    """
    return (info.external_attr >> 16) & _UNIX_TYPE_MASK == stat.S_IFLNK


def validate_zip_safety(
    zf: zipfile.ZipFile,
    *,
    max_entries: int | None = None,
    max_total_size: int | None = None,
) -> None:
    """Validate that the archive contains no symlinks and is within caps.

    Symlinks are rejected unconditionally: even when the extractor does
    not honor them, future code changes or shell-out extraction can
    silently turn them into a write-anywhere primitive, so we refuse
    them at the boundary.

    Args:
        zf: An open ZipFile to validate.
        max_entries: Maximum number of archive entries.  ``None`` disables
            the check.
        max_total_size: Maximum *header-reported* total uncompressed size
            in bytes.  ``None`` disables the check.  (Header values are
            self-reported; callers that need bomb-resistant decompression
            should also cap per-read sizes.)

    Raises:
        ValueError: If any entry is a symlink, or a cap is exceeded.
    """
    entries = zf.infolist()

    if max_entries is not None and len(entries) > max_entries:
        raise ValueError(f"Zip archive contains {len(entries)} entries, exceeding limit of {max_entries}")

    if max_total_size is not None:
        total = sum(info.file_size for info in entries)
        if total > max_total_size:
            raise ValueError(
                f"Total uncompressed size ({total // (1024 * 1024)} MB) "
                f"exceeds limit of {max_total_size // (1024 * 1024)} MB"
            )

    for info in entries:
        if _is_symlink(info):
            raise ValueError(f"Zip entry is a symlink (security risk): {info.filename!r}")


def validate_zip_entries(
    zf: zipfile.ZipFile,
    target_dir: str,
    *,
    max_entries: int | None = None,
    max_total_size: int | None = None,
) -> None:
    """Validate that no zip entries escape *target_dir* (zip-slip).

    Runs all checks in :func:`validate_zip_safety` and additionally
    verifies that every entry resolves to a path inside *target_dir*.
    This prevents zip-slip attacks where entries like ``../../.bashrc``
    write outside the intended location.

    Args:
        zf: An open ZipFile to validate.
        target_dir: The directory entries will be extracted into.
        max_entries: Maximum number of archive entries (forwarded to
            :func:`validate_zip_safety`).
        max_total_size: Maximum total uncompressed size in bytes
            (forwarded to :func:`validate_zip_safety`).

    Raises:
        ValueError: On any safety violation: symlink, cap exceeded, or
            path resolving outside *target_dir*.
    """
    validate_zip_safety(zf, max_entries=max_entries, max_total_size=max_total_size)

    normalized_target = os.path.normpath(target_dir)
    safe_prefix = normalized_target + os.sep

    for info in zf.infolist():
        resolved = os.path.normpath(os.path.join(target_dir, info.filename))
        # Allow the target dir itself (for directory entries named ".")
        if resolved != normalized_target and not resolved.startswith(safe_prefix):
            raise ValueError(f"Zip entry escapes target directory: {info.filename!r}")
