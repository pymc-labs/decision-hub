"""Shared utilities for cloning repos, discovering skills, and creating zips.

Used by both the tracker service (auto-republish) and the GitHub crawler.
"""

import io
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from dhub_core.validation import bump_version, parse_semver  # noqa: F401 — re-exported

CLONE_TIMEOUT_SECONDS = 120


def clone_repo(
    clone_url: str,
    branch: str = "HEAD",
    *,
    github_token: str | None = None,
    timeout: int = CLONE_TIMEOUT_SECONDS,
) -> Path:
    """Clone a git repo (shallow, depth=1) into a temp directory.

    When a github_token is provided, rewrites the URL to use HTTPS
    token authentication (supports private repos).

    Returns the path to the cloned repo root.

    Raises:
        RuntimeError: If clone times out (sanitized to avoid leaking tokens).
        subprocess.CalledProcessError: If clone fails.
    """
    if github_token:
        clone_url = _build_authenticated_url(clone_url, github_token)

    tmp_dir = Path(tempfile.mkdtemp(prefix="dhub-clone-"))
    cmd = ["git", "clone", "--depth", "1"]
    if branch != "HEAD":
        cmd.extend(["--branch", branch])
    cmd.extend([clone_url, str(tmp_dir / "repo")])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # Clean up and raise a sanitized error (TimeoutExpired includes
        # the full cmd list which may contain the github_token in the URL)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError(f"git clone timed out after {timeout}s") from None
    if result.returncode != 0:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        stderr = result.stderr.strip()
        if github_token:
            stderr = stderr.replace(github_token, "***")
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd[0],
            output=result.stdout,
            stderr=stderr,
        )
    return tmp_dir / "repo"


def discover_skills(root: Path) -> list[Path]:
    """Find skill directories (containing valid SKILL.md) under a root path.

    Skips hidden directories, node_modules, and __pycache__.
    Only includes directories where SKILL.md parses successfully.
    """
    import yaml

    from decision_hub.domain.skill_manifest import parse_skill_md

    skill_dirs: list[Path] = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        parts = skill_md.relative_to(root).parts
        if any(p.startswith(".") or p in ("node_modules", "__pycache__") for p in parts):
            continue
        try:
            parse_skill_md(skill_md)
            skill_dirs.append(skill_md.parent)
        except (ValueError, FileNotFoundError, yaml.YAMLError):
            continue
    return skill_dirs


def create_zip(path: Path) -> bytes:
    """Create an in-memory zip archive of a skill directory.

    Excludes hidden files/directories and __pycache__.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(path.rglob("*")):
            if not file.is_file():
                continue
            relative = file.relative_to(path)
            parts = relative.parts
            if any(part.startswith(".") or part == "__pycache__" for part in parts):
                continue
            zf.write(file, relative)
    return buf.getvalue()


def _build_authenticated_url(repo_url: str, token: str) -> str:
    """Rewrite a GitHub repo URL to use HTTPS token authentication."""
    from decision_hub.domain.tracker import parse_github_repo_url

    owner, repo = parse_github_repo_url(repo_url)
    return f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
