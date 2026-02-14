"""Publishing validation for skills."""

import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from dhub_core.validation import validate_semver, validate_skill_name

__all__ = [
    "CODE_EXTENSIONS",
    "CONFIG_EXTENSIONS",
    "SCANNABLE_EXTENSIONS",
    "TEXT_EXTENSIONS",
    "EvaluationBundle",
    "build_quarantine_s3_key",
    "build_s3_key",
    "extract_for_evaluation",
    "validate_semver",
    "validate_skill_name",
]


# ---------------------------------------------------------------------------
# File extension categories for scannable content
# ---------------------------------------------------------------------------

TEXT_EXTENSIONS = frozenset({".md", ".mdx", ".txt", ".latex", ".dot"})
CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".sh",
        ".ps1",
        ".rb",
        ".R",
        ".go",
        ".gd",
        ".sql",
        ".html",
        ".bicep",
        ".svg",
        ".glsl",
    }
)
CONFIG_EXTENSIONS = frozenset(
    {
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".xml",
        ".ini",
        ".conf",
        ".template",
        ".j2",
        ".lock",
    }
)
SCANNABLE_EXTENSIONS = TEXT_EXTENSIONS | CODE_EXTENSIONS | CONFIG_EXTENSIONS


@dataclass(frozen=True)
class EvaluationBundle:
    """All content extracted from a skill zip for evaluation."""

    skill_md_content: str
    source_files: list[tuple[str, str]]  # code files (filename, content)
    lockfile_content: str | None
    zip_entries: list[tuple[str, int, str]]  # (filename, uncompressed_size, extension)


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


def extract_for_evaluation(
    zip_bytes: bytes,
) -> EvaluationBundle:
    """Extract evaluation-relevant files from a skill zip archive.

    Reads SKILL.md, Python source files, and the lockfile (if present)
    from the in-memory zip without writing to disk.  Collects per-entry
    metadata (filename, uncompressed size, extension) for the size-budget
    check.

    Note: Phase 2 will expand extraction to all CODE_EXTENSIONS files
    and add text_files / config_files to the bundle.

    Args:
        zip_bytes: Raw bytes of the skill zip archive.

    Returns:
        An EvaluationBundle with all extracted content and zip metadata.

    Raises:
        ValueError: If the zip does not contain a SKILL.md file, if any
            individual file exceeds the size limit, or if total extracted
            size or entry count exceeds limits (zip bomb prevention).
    """
    skill_md = ""
    source_files: list[tuple[str, str]] = []
    lockfile_content: str | None = None
    zip_entries: list[tuple[str, int, str]] = []

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        entries = zf.infolist()

        # Zip bomb prevention: check entry count and total uncompressed size
        if len(entries) > _MAX_ZIP_ENTRIES:
            raise ValueError(f"Zip archive contains {len(entries)} entries, exceeding limit of {_MAX_ZIP_ENTRIES}")

        total_uncompressed = sum(info.file_size for info in entries)
        if total_uncompressed > _MAX_TOTAL_EXTRACTED:
            raise ValueError(
                f"Total uncompressed size ({total_uncompressed // (1024 * 1024)} MB) "
                f"exceeds limit of {_MAX_TOTAL_EXTRACTED // (1024 * 1024)} MB"
            )

        for name in zf.namelist():
            if name.endswith("/"):
                continue

            info = zf.getinfo(name)
            if info.file_size > _MAX_FILE_SIZE:
                raise ValueError(f"File '{name}' exceeds maximum size of {_MAX_FILE_SIZE // (1024 * 1024)} MB")

            ext = PurePosixPath(name).suffix.lower()
            basename = name.rsplit("/", 1)[-1] if "/" in name else name

            # Track zip metadata for size budget check
            zip_entries.append((name, info.file_size, ext))

            if basename == "SKILL.md":
                skill_md = zf.read(name).decode()
            elif basename.endswith(".py"):
                source_files.append((name, zf.read(name).decode()))
            elif basename in ("requirements.txt", "uv.lock", "poetry.lock"):
                lockfile_content = zf.read(name).decode()

    if not skill_md:
        raise ValueError("Zip archive does not contain a SKILL.md file")

    return EvaluationBundle(
        skill_md_content=skill_md,
        source_files=source_files,
        lockfile_content=lockfile_content,
        zip_entries=zip_entries,
    )
