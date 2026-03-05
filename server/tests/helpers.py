"""Shared test helpers for server tests.

Reusable utility functions extracted from individual test modules to
eliminate duplication. Import these into test files instead of
redefining them locally.
"""

import io
import zipfile


def make_skill_zip(
    skill_md: str = "---\nname: my-skill\ndescription: A test skill\n---\nbody\n",
    sources: dict[str, str] | None = None,
    lockfile: str | None = None,
) -> bytes:
    """Create an in-memory zip archive with SKILL.md and optional files.

    Args:
        skill_md: Content of the SKILL.md file.
        sources: Mapping of filename to content for additional source files.
        lockfile: Content of a requirements.txt lockfile (if any).

    Returns:
        Raw bytes of the zip archive.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", skill_md)
        for name, content in (sources or {}).items():
            zf.writestr(name, content)
        if lockfile is not None:
            zf.writestr("requirements.txt", lockfile)
    return buf.getvalue()
