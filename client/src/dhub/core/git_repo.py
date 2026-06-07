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

# Hard ceiling for git clone/checkout so an unreachable or hung remote
# can't lock the CLI forever. Five minutes comfortably covers cold clones
# of large repos on slow networks while still failing within the user's
# patience window.
_GIT_TIMEOUT_SECONDS = 300


def _run_git(cmd: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a git subprocess with a bounded timeout.

    Returns the completed process on success or timeout-converted to a
    ``RuntimeError`` so callers can surface a clean message instead of
    hanging forever. Stdout/stderr are captured so secrets the user may
    have set on the URL never end up on the user's terminal.
    """
    try:
        return subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git command timed out after {_GIT_TIMEOUT_SECONDS}s: {' '.join(cmd[:2])} ...") from exc


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
            result = _run_git(["git", "clone", repo_url, str(repo_path)])
            if result.returncode != 0:
                raise RuntimeError(f"git clone failed (exit {result.returncode}):\n{result.stderr.strip()}")
            checkout = _run_git(["git", "checkout", ref], cwd=str(repo_path))
            if checkout.returncode != 0:
                raise RuntimeError(f"git checkout {ref} failed:\n{checkout.stderr.strip()}")
        else:
            cmd = ["git", "clone", "--depth", "1"]
            if ref:
                cmd += ["--branch", ref]
            cmd += [repo_url, str(repo_path)]
            result = _run_git(cmd)
            if result.returncode != 0:
                raise RuntimeError(f"git clone failed (exit {result.returncode}):\n{result.stderr.strip()}")
    except Exception:
        # Any failure leaves no usable checkout, so clean the tempdir to
        # avoid leaking partial clones into /tmp.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

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
