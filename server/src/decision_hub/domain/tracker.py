"""Domain logic for skill update tracking.

Pure functions for parsing GitHub repo URLs and checking for new commits.
"""

import re

import httpx

# Matches GitHub HTTPS URLs like:
#   https://github.com/owner/repo
#   https://github.com/owner/repo.git
_GITHUB_HTTPS_PATTERN = re.compile(
    r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?/?$"
)

# Matches GitHub SSH URLs like:
#   git@github.com:owner/repo.git
_GITHUB_SSH_PATTERN = re.compile(
    r"git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/.]+?)(?:\.git)?$"
)


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
        f"Not a GitHub repo URL: {url}. "
        "Expected https://github.com/owner/repo or git@github.com:owner/repo.git"
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
    headers = {"Accept": "application/vnd.github.v3+json"}
    if github_token:
        headers["Authorization"] = f"token {github_token}"

    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}",
            headers=headers,
        )
        resp.raise_for_status()

    return resp.json()["sha"]


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
