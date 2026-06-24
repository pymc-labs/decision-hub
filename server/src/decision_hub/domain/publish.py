"""Publishing validation for skills."""

import io
import os
import zipfile

from dhub_core.validation import validate_semver, validate_skill_name

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


def _safe_read(zf: zipfile.ZipFile, name: str, remaining_budget: int) -> bytes:
    """Read a zip member while enforcing per-file and remaining-total caps.

    ZipInfo.file_size is taken from the central directory, which the
    archive can lie about. Reading via zf.open() and accumulating the
    actual decompressed bytes is the only honest way to bound a zip-bomb.
    """
    cap = min(_MAX_FILE_SIZE, remaining_budget) + 1
    with zf.open(name) as fh:
        data = fh.read(cap)
    if len(data) > _MAX_FILE_SIZE:
        raise ValueError(f"File '{name}' exceeds maximum size of {_MAX_FILE_SIZE // (1024 * 1024)} MB")
    if len(data) > remaining_budget:
        raise ValueError(f"Total uncompressed size exceeds limit of {_MAX_TOTAL_EXTRACTED // (1024 * 1024)} MB")
    return data


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
        entries = zf.infolist()

        # Zip bomb prevention: bound the entry count immediately.  The
        # per-file and total-size budgets are enforced during read, since
        # ZipInfo.file_size is attacker-controlled metadata.
        if len(entries) > _MAX_ZIP_ENTRIES:
            raise ValueError(f"Zip archive contains {len(entries)} entries, exceeding limit of {_MAX_ZIP_ENTRIES}")

        remaining_budget = _MAX_TOTAL_EXTRACTED
        for name in zf.namelist():
            if name.endswith("/"):
                continue

            basename = name.rsplit("/", 1)[-1] if "/" in name else name

            if basename == "SKILL.md":
                data = _safe_read(zf, name, remaining_budget)
                remaining_budget -= len(data)
                skill_md = data.decode()
            elif basename in ("requirements.txt", "uv.lock", "poetry.lock"):
                data = _safe_read(zf, name, remaining_budget)
                remaining_budget -= len(data)
                lockfile_content = data.decode()
            elif _is_scannable_file(basename):
                data = _safe_read(zf, name, remaining_budget)
                remaining_budget -= len(data)
                source_files.append((name, data.decode()))
            else:
                unscanned_files.append(name)

    if not skill_md:
        raise ValueError("Zip archive does not contain a SKILL.md file")

    # Sort smallest files first so small malicious files aren't pushed out
    # by large benign padding files when hitting downstream size caps
    source_files.sort(key=lambda fc: len(fc[1]))

    return skill_md, source_files, lockfile_content, unscanned_files
