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

# Maximum time (seconds) to allow a `git` subprocess call before we give
# up. Repositories can legitimately be large, but a hung DNS lookup or
# stalled fetch used to freeze the CLI forever inside `console.status(...)`
# with no feedback.
_GIT_TIMEOUT_SECONDS = 300


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


def _strip_credentials(url: str) -> str:
    """Remove ``userinfo@`` from an HTTP(S) URL.

    A user-supplied URL such as ``https://<pat>@github.com/owner/repo``
    would otherwise land on the subprocess argv (visible to any local
    user via ``ps -e``) and inside error messages surfaced back to the
    caller. This scrubs both.
    """
    return re.sub(r"^(https?://)[^/@]+@", r"\1", url)


def _redact_url_in_text(text: str, original_url: str) -> str:
    """Best-effort scrub of the credentialed URL from a subprocess stderr string.

    git happily echoes the full URL (including any embedded PAT) back
    into its own error messages. Replace any occurrence of the original,
    credentialed URL with its stripped form before we hand the message
    to the user or write it into an exception.
    """
    if not text:
        return text
    stripped = _strip_credentials(original_url)
    if stripped != original_url:
        text = text.replace(original_url, stripped)
    # Also catch the pattern generically in case git rewrote the URL
    # (e.g. added `.git`) before printing.
    return re.sub(r"(https?://)[^/@\s]+@", r"\1", text)


def _run_git(cmd: list[str], repo_url: str, *, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Invoke `git` with a hard timeout and credential-scrubbed error text.

    Raises ``RuntimeError`` on non-zero exit or timeout. Never re-raises
    the original ``subprocess.TimeoutExpired`` or ``FileNotFoundError``
    because those exceptions embed the argv (with credentials).
    """
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git {cmd[1] if len(cmd) > 1 else ''} timed out after {_GIT_TIMEOUT_SECONDS}s") from exc
    except FileNotFoundError as exc:
        # `git` binary missing on PATH — give a clear error rather than
        # a stringified FileNotFoundError that shows the argv.
        raise RuntimeError("git executable not found on PATH") from exc


def clone_repo(repo_url: str, ref: str | None = None) -> Path:
    """Clone a git repository into a temporary directory.

    Args:
        repo_url: Git-cloneable URL (HTTPS or SSH). May include an
            embedded PAT which will be scrubbed from argv and errors.
        ref: Optional branch, tag, or commit SHA to checkout.

    Returns:
        Path to the cloned repository root.

    Raises:
        RuntimeError: If the clone or checkout fails, or times out.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="dhub-repo-"))
    repo_path = tmp_dir / "repo"

    if ref and _looks_like_sha(ref):
        # Commit SHAs don't work with --depth 1 --branch; do a full
        # clone then checkout the specific commit.
        cmd = ["git", "clone", repo_url, str(repo_path)]
        result = _run_git(cmd, repo_url)
        if result.returncode != 0:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError(
                f"git clone failed (exit {result.returncode}):\n{_redact_url_in_text(result.stderr.strip(), repo_url)}"
            )
        checkout = _run_git(["git", "checkout", ref], repo_url, cwd=str(repo_path))
        if checkout.returncode != 0:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError(f"git checkout {ref} failed:\n{_redact_url_in_text(checkout.stderr.strip(), repo_url)}")
    else:
        cmd = ["git", "clone", "--depth", "1"]
        if ref:
            cmd += ["--branch", ref]
        cmd += [repo_url, str(repo_path)]
        result = _run_git(cmd, repo_url)
        if result.returncode != 0:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise RuntimeError(
                f"git clone failed (exit {result.returncode}):\n{_redact_url_in_text(result.stderr.strip(), repo_url)}"
            )

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
