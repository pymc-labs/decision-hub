"""Clone a git repository and discover skills within it.

A skill is any directory containing a valid SKILL.md file with
proper YAML frontmatter (name + description fields).
"""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_GIT_URL_PREFIXES = ("https://", "http://", "git@", "ssh://", "git://")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")


def looks_like_git_url(value: str) -> bool:
    """Return True if *value* looks like a git-cloneable URL rather than a local path or org/skill ref."""
    if any(value.startswith(prefix) for prefix in _GIT_URL_PREFIXES):
        return True
    return bool(value.endswith(".git"))


def _looks_like_sha(ref: str) -> bool:
    """Return True if ref looks like a commit SHA (7-40 hex chars)."""
    return bool(_SHA_PATTERN.match(ref))


def clone_repo(repo_url: str, ref: str | None = None) -> Path:
    """Clone a git repository into a temporary directory.

    Args:
        repo_url: Git-cloneable URL (HTTPS or SSH).
        ref: Optional branch, tag, or commit SHA to checkout.

    Returns:
        Path to the cloned repository root.

    Raises:
        RuntimeError: If the clone or checkout fails.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="dhub-repo-"))
    repo_path = tmp_dir / "repo"

    if ref and _looks_like_sha(ref):
        # Commit SHAs don't work with --depth 1 --branch; do a full
        # clone then checkout the specific commit.
        cmd = ["git", "clone", repo_url, str(repo_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError(f"git clone failed (exit {result.returncode}):\n{result.stderr.strip()}")
        checkout = subprocess.run(
            ["git", "checkout", ref],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
        )
        if checkout.returncode != 0:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError(f"git checkout {ref} failed:\n{checkout.stderr.strip()}")
    else:
        cmd = ["git", "clone", "--depth", "1"]
        if ref:
            cmd += ["--branch", ref]
        cmd += [repo_url, str(repo_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError(f"git clone failed (exit {result.returncode}):\n{result.stderr.strip()}")

    return repo_path


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
