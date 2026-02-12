"""GitHub URL parsing and commit SHA checking for skill trackers."""

import re

import httpx

# Matches GitHub HTTPS URLs like:
#   https://github.com/owner/repo
#   https://github.com/owner/repo.git
_GITHUB_HTTPS_PATTERN = re.compile(r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")

# Matches GitHub SSH URLs like:
#   git@github.com:owner/repo.git
_GITHUB_SSH_PATTERN = re.compile(r"git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$")


def build_canonical_repo_url(owner: str, repo: str) -> str:
    """Build a canonical HTTPS GitHub URL from owner and repo name."""
    return f"https://github.com/{owner}/{repo}"


def parse_github_repo_url(url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub URL.

    Supports HTTPS and SSH formats.

    Raises:
        ValueError: If the URL is not a recognized GitHub repo URL.
    """
    for pattern in (_GITHUB_HTTPS_PATTERN, _GITHUB_SSH_PATTERN):
        match = pattern.match(url)
        if match:
            return match.group("owner"), match.group("repo")
    raise ValueError(
        f"Not a GitHub repo URL: {url}. Expected https://github.com/owner/repo or git@github.com:owner/repo.git"
    )


def fetch_latest_commit_sha(
    owner: str,
    repo: str,
    branch: str = "main",
    github_token: str | None = None,
) -> str:
    """Fetch the latest commit SHA for a branch from the GitHub API.

    Args:
        owner: GitHub repo owner.
        repo: GitHub repo name.
        branch: Branch name to check.
        github_token: Optional GitHub token for private repos / higher rate limits.

    Returns:
        The full 40-char commit SHA.

    Raises:
        httpx.HTTPStatusError: On API errors (404 for missing repo/branch, 403 for rate limit).
    """
    headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}",
            headers=headers,
        )
        resp.raise_for_status()

    return resp.json()["sha"]


def check_repo_accessible(
    owner: str,
    repo: str,
    github_token: str | None = None,
) -> bool:
    """Check if a GitHub repo is accessible (returns True for public or auth'd private repos).

    Makes a lightweight HEAD-style request to the GitHub API.
    Returns False for 404 (private without auth) or 403 (rate-limited / forbidden).
    """
    headers: dict[str, str] = {"Accept": "application/vnd.github.v3+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers=headers,
            )
            return resp.status_code == 200
    except httpx.HTTPError:
        return False


def has_new_commits(
    owner: str,
    repo: str,
    branch: str,
    last_known_sha: str | None,
    github_token: str | None = None,
) -> tuple[bool, str]:
    """Check if a branch has new commits since a known SHA.

    Returns (changed, current_sha). If last_known_sha is None (first check),
    always returns changed=True.
    """
    current_sha = fetch_latest_commit_sha(owner, repo, branch, github_token)
    if last_known_sha is None:
        return True, current_sha
    return current_sha != last_known_sha, current_sha
