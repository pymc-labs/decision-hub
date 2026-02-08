"""Clone a git repository and discover skills within it.

A skill is any directory containing a valid SKILL.md file with
proper YAML frontmatter (name + description fields).
"""

import subprocess
import tempfile
from pathlib import Path


def clone_repo(repo_url: str, ref: str | None = None) -> Path:
    """Clone a git repository into a temporary directory.

    Args:
        repo_url: Git-cloneable URL (HTTPS or SSH).
        ref: Optional branch, tag, or commit to checkout.

    Returns:
        Path to the cloned repository root.

    Raises:
        RuntimeError: If the clone or checkout fails.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="dhub-repo-"))
    cmd = ["git", "clone", "--depth", "1"]
    if ref:
        cmd += ["--branch", ref]
    cmd += [repo_url, str(tmp_dir / "repo")]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"git clone failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )

    return tmp_dir / "repo"


def discover_skills(root: Path) -> list[Path]:
    """Find all skill directories under a root path.

    A skill directory is any directory that contains a SKILL.md file
    with valid YAML frontmatter (parseable name and description).

    Args:
        root: Root directory to search.

    Returns:
        Sorted list of paths to directories containing valid SKILL.md files.
    """
    from dhub.core.manifest import parse_skill_md

    skill_dirs: list[Path] = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        # Skip hidden directories and common non-skill locations
        parts = skill_md.relative_to(root).parts
        if any(p.startswith(".") or p == "node_modules" or p == "__pycache__" for p in parts):
            continue

        try:
            parse_skill_md(skill_md)
            skill_dirs.append(skill_md.parent)
        except (ValueError, FileNotFoundError):
            # Not a valid skill — skip silently
            continue

    return skill_dirs
