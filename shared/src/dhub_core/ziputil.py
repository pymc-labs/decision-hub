"""Zip archive safety utilities.

Provides path-traversal validation for zip extraction to prevent
zip-slip attacks where malicious entries escape the target directory.
"""

import os
import stat
import zipfile

# Unix file-mode bits live in the upper 16 bits of external_attr for
# entries created on Unix systems (create_system == 3).  The type
# nibble (S_IFMT) distinguishes regular files, directories, symlinks,
# device nodes, etc.
_S_IFMT_SHIFT = 16


def _entry_file_type(info: zipfile.ZipInfo) -> int:
    """Return the Unix file-type bits (S_IFMT) of a zip entry, or 0.

    Returns 0 when:
      - the entry was written on a non-Unix system (no Unix mode), or
      - no S_IFMT type bits were set (Python's ``writestr`` defaults
        to permission bits only, with no file type).

    Callers can treat a zero return as "regular file" and only reject
    explicitly-tagged special files (symlinks, devices, sockets).
    """
    if info.create_system != 3:
        return 0
    mode = (info.external_attr >> _S_IFMT_SHIFT) & 0xFFFF
    return mode & 0o170000  # S_IFMT mask


def validate_zip_entries(zf: zipfile.ZipFile, target_dir: str) -> None:
    """Validate that no zip entries escape the target directory.

    Checks every entry in the archive to ensure its resolved path
    stays within *target_dir*.  This prevents zip-slip attacks where
    entries like ``../../.bashrc`` write outside the intended location.

    Also rejects symlink and other special-file entries as a
    defense-in-depth measure: Python's ``zipfile.extractall`` writes
    the link target as a regular file's content (no escape), but
    other extractors (system ``unzip``, custom tooling) honor the
    symlink mode bits and would let an entry like ``link -> /etc``
    redirect later writes outside the sandbox.

    Args:
        zf: An open ZipFile to validate.
        target_dir: The directory entries will be extracted into.

    Raises:
        ValueError: If any entry resolves outside target_dir or
            declares a symlink / non-regular file mode.
    """
    safe_prefix = os.path.normpath(target_dir) + os.sep
    allowed_types = (stat.S_IFREG, stat.S_IFDIR)

    for info in zf.infolist():
        file_type = _entry_file_type(info)
        if file_type and file_type not in allowed_types:
            raise ValueError(f"Zip entry has unsupported file type (mode={oct(file_type)}): {info.filename!r}")

        resolved = os.path.normpath(os.path.join(target_dir, info.filename))
        # Allow the target dir itself (for directory entries named ".")
        if resolved != os.path.normpath(target_dir) and not resolved.startswith(safe_prefix):
            raise ValueError(f"Zip entry escapes target directory: {info.filename!r}")
