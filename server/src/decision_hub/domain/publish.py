"""Publishing validation for skills."""

import io
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


def extract_for_evaluation(
    zip_bytes: bytes,
) -> tuple[str, list[tuple[str, str]], str | None]:
    """Extract evaluation-relevant files from a skill zip archive.

    Reads SKILL.md, all .py source files, and the lockfile (if present)
    from the in-memory zip without writing to disk.

    Args:
        zip_bytes: Raw bytes of the skill zip archive.

    Returns:
        A tuple of (skill_md_content, source_files, lockfile_content) where
        source_files is a list of (filename, content) tuples and
        lockfile_content is None if no lockfile was found.

    Raises:
        ValueError: If the zip does not contain a SKILL.md file, or if any
            individual file exceeds the size limit.
    """
    skill_md = ""
    source_files: list[tuple[str, str]] = []
    lockfile_content: str | None = None

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue

            if zf.getinfo(name).file_size > _MAX_FILE_SIZE:
                raise ValueError(f"File '{name}' exceeds maximum size of {_MAX_FILE_SIZE // (1024 * 1024)} MB")

            basename = name.rsplit("/", 1)[-1] if "/" in name else name

            if basename == "SKILL.md":
                skill_md = zf.read(name).decode()
            elif basename.endswith(".py"):
                source_files.append((name, zf.read(name).decode()))
            elif basename in ("requirements.txt", "uv.lock", "poetry.lock"):
                lockfile_content = zf.read(name).decode()

    if not skill_md:
        raise ValueError("Zip archive does not contain a SKILL.md file")

    return skill_md, source_files, lockfile_content
