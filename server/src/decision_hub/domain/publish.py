"""Publishing validation for skills."""

import io
import os
import zipfile

from dhub_core.validation import validate_semver, validate_skill_name
from dhub_core.ziputil import validate_zip_safety

__all__ = ["validate_semver", "validate_skill_name"]


def build_s3_key(org_slug: str, skill_name: str, version: str) -> str:
    """Build the S3 object key for a published skill version.

    Args:
        org_slug: The organization slug.
        skill_name: The skill name.
        version: The semver version string.

    Returns:
        S3 key in the format 'skills/{org}/{name}/{version}.zip'.
    """
    return f"skills/{org_slug}/{skill_name}/{version}.zip"


def build_quarantine_s3_key(org_slug: str, skill_name: str, version: str) -> str:
    """Build the S3 object key for a rejected skill stored in quarantine.

    Rejected (Grade F) packages are stored under a 'rejected/' prefix
    for forensic inspection while kept separate from published skills.

    Returns:
        S3 key in the format 'rejected/{org}/{name}/{version}.zip'.
    """
    return f"rejected/{org_slug}/{skill_name}/{version}.zip"


_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB per extracted file
_MAX_TOTAL_EXTRACTED = 100 * 1024 * 1024  # 100 MB total uncompressed
_MAX_ZIP_ENTRIES = 500  # maximum number of entries in the zip

# File types to extract for security scanning
_SECURITY_SCAN_EXTENSIONS = frozenset(
    {
        ".py",
        ".sh",
        ".bash",
        ".zsh",  # scripts
        ".js",
        ".ts",
        ".tsx",
        ".cs",  # compiled/transpiled code
        ".json",
        ".yml",
        ".yaml",  # config
        ".md",
        ".txt",  # text/docs
    }
)
_SECURITY_SCAN_NAMES = frozenset({"Makefile", "Dockerfile", ".env", "LICENSE"})


def _is_scannable_file(basename: str) -> bool:
    """Check if a file should be extracted for security scanning."""
    if basename in _SECURITY_SCAN_NAMES:
        return True
    _, ext = os.path.splitext(basename)
    return ext in _SECURITY_SCAN_EXTENSIONS


def extract_for_evaluation(
    zip_bytes: bytes,
) -> tuple[str, list[tuple[str, str]], str | None, list[str]]:
    """Extract evaluation-relevant files from a skill zip archive.

    Reads SKILL.md, scannable source files (.py, .sh, .json, .yml, etc.),
    and the lockfile (if present) from the in-memory zip without writing
    to disk.  Also tracks filenames that were skipped (not scannable).

    Args:
        zip_bytes: Raw bytes of the skill zip archive.

    Returns:
        A tuple of (skill_md_content, source_files, lockfile_content,
        unscanned_files) where source_files is a list of (filename, content)
        tuples, lockfile_content is None if no lockfile was found, and
        unscanned_files is a list of filenames that were not extracted
        for security scanning.

    Raises:
        ValueError: If the zip does not contain a SKILL.md file, if any
            individual file exceeds the size limit, or if total extracted
            size or entry count exceeds limits (zip bomb prevention).
    """
    skill_md = ""
    source_files: list[tuple[str, str]] = []
    lockfile_content: str | None = None
    unscanned_files: list[str] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        # Reject symlinks and enforce zip-bomb caps before reading any
        # entries.  The extractor never writes to disk, but symlinks
        # would point downstream code at arbitrary files if anyone
        # later persists ``source_files`` to disk, so we refuse them
        # at the boundary.
        validate_zip_safety(zf, max_entries=_MAX_ZIP_ENTRIES, max_total_size=_MAX_TOTAL_EXTRACTED)

        for info in zf.infolist():
            if info.is_dir():
                continue

            if info.file_size > _MAX_FILE_SIZE:
                raise ValueError(f"File '{info.filename}' exceeds maximum size of {_MAX_FILE_SIZE // (1024 * 1024)} MB")

            basename = os.path.basename(info.filename)

            if basename == "SKILL.md":
                skill_md = zf.read(info).decode()
            elif basename in ("requirements.txt", "uv.lock", "poetry.lock"):
                lockfile_content = zf.read(info).decode()
            elif _is_scannable_file(basename):
                source_files.append((info.filename, zf.read(info).decode()))
            else:
                unscanned_files.append(info.filename)

    if not skill_md:
        raise ValueError("Zip archive does not contain a SKILL.md file")

    # Sort smallest files first so small malicious files aren't pushed out
    # by large benign padding files when hitting downstream size caps
    source_files.sort(key=lambda fc: len(fc[1]))

    return skill_md, source_files, lockfile_content, unscanned_files
