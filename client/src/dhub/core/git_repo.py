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

# Bound each ``git`` subprocess call. A slow or hostile remote can
# otherwise hang ``dhub publish <git-url>`` indefinitely with no
# feedback to the user (the surrounding console.status spinner just
# keeps spinning).
_GIT_TIMEOUT_SECONDS = 180


def git_url_to_https(url: str) -> str | None:
    """Convert a git-cloneable URL to an HTTPS browse URL.

    Handles SSH (git@github.com:owner/repo.git), HTTPS, and git:// formats.
    Returns None if the URL can't be converted.
    """
    # SSH format: git@github.com:owner/repo.git
    m = re.match(r"^git@([^:]+):(.+?)(?:\.git)?$", url)
    if m:
        return f"https://{m.group(1)}/{m.group(2)}"

    # HTTPS/git:// format: strip .git suffix and userinfo
    for prefix in ("https://", "http://", "git://", "ssh://"):
        if url.startswith(prefix):
            clean = url.removesuffix(".git")
            if prefix in ("git://", "ssh://", "http://"):
                clean = clean.replace(prefix, "https://", 1)
            # Strip userinfo (e.g. git@ in ssh://git@github.com/...)
            clean = re.sub(r"^(https?://)([^@]+@)", r"\1", clean)
            return clean

    return None


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

    try:
        if ref and _looks_like_sha(ref):
            # Commit SHAs don't work with --depth 1 --branch; do a full
            # clone then checkout the specific commit.
            _run_git(["git", "clone", repo_url, str(repo_path)])
            _run_git(["git", "checkout", ref], cwd=str(repo_path), fail_msg=f"git checkout {ref} failed")
        else:
            cmd = ["git", "clone", "--depth", "1"]
            if ref:
                cmd += ["--branch", ref]
            cmd += [repo_url, str(repo_path)]
            _run_git(cmd)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    return repo_path


def _run_git(cmd: list[str], *, cwd: str | None = None, fail_msg: str = "git clone failed") -> None:
    """Run a git subprocess with a bounded timeout and clean error messages."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{fail_msg}: timed out after {_GIT_TIMEOUT_SECONDS}s. The remote may be slow or unreachable."
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(f"{fail_msg} (exit {result.returncode}):\n{result.stderr.strip()}")


def discover_skills(root: Path) -> list[Path]:
    """Find all skill directories under a root path.

    A skill directory is any directory that contains a SKILL.md file
    with valid YAML frontmatter (parseable name and description).

    Symlinks are not followed -- a directory symlink pointing back into
    the tree (``a/link -> ..``) would otherwise cause ``rglob`` to loop
    until Python's own recursion protection kicks in, and a symlink
    pointing *out* of the tree would double-publish skills under
    misleading paths.

    Args:
        root: Root directory to search.

    Returns:
        Sorted list of paths to directories containing valid SKILL.md files.
    """
    import os

    from dhub.core.manifest import parse_skill_md

    skill_dirs: list[Path] = []
    # os.walk with followlinks=False respects both file and directory
    # symlinks; pathlib.Path.rglob does not expose that switch.
    for current_dir, subdirs, files in os.walk(root, followlinks=False):
        # Prune hidden / build directories in-place so os.walk skips them.
        subdirs[:] = [d for d in subdirs if not (d.startswith(".") or d == "node_modules" or d == "__pycache__")]

        if "SKILL.md" not in files:
            continue

        skill_md = Path(current_dir) / "SKILL.md"
        # Skip if the SKILL.md itself is a symlink (avoid target confusion).
        if skill_md.is_symlink():
            continue

        try:
            parse_skill_md(skill_md)
            skill_dirs.append(skill_md.parent)
        except (ValueError, FileNotFoundError):
            # Not a valid skill — skip silently
            continue

    return sorted(skill_dirs)
