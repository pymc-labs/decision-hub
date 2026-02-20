"""Rate-limit-aware HTTP client for the GitHub REST and GraphQL APIs."""

import time
from types import TracebackType

import httpx
from loguru import logger

GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"

# Maximum aliases per GraphQL request (GitHub hard-limits at 500 nodes).
_GRAPHQL_BATCH_CHUNK = 250


class GitHubClient:
    """Rate-limit-aware HTTP client for the GitHub API.

    Supports both REST (``get``) and GraphQL (``graphql``) calls, with
    automatic rate-limit backoff for both.

    Use as a context manager::

        with GitHubClient(token="ghp_...") as gh:
            resp = gh.get("/repos/owner/repo")
    """

    def __init__(self, token: str | None = None):
        headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=GITHUB_API,
            headers=headers,
            timeout=30,
        )
        self._token = token
        self._rate_limit_remaining = 999
        self._rate_limit_reset = 0.0

    # -- context manager -----------------------------------------------------

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        self._client.close()

    # -- REST -----------------------------------------------------------------

    def get(self, path: str, params: dict | None = None) -> httpx.Response:
        self._wait_for_rate_limit()
        resp = self._client.get(path, params=params)
        self._update_rate_limit(resp)
        if resp.status_code == 403 and "rate limit" in resp.text.lower():
            wait = max(self._rate_limit_reset - time.time(), 5)
            logger.warning("Rate limited. Waiting {:.0f}s...", wait)
            time.sleep(wait + 1)
            resp = self._client.get(path, params=params)
            self._update_rate_limit(resp)
        return resp

    # -- GraphQL --------------------------------------------------------------

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        """Execute a GraphQL query against the GitHub API.

        Raises ``httpx.HTTPStatusError`` on non-2xx responses and
        ``ValueError`` when the response contains GraphQL-level errors.
        """
        self._wait_for_rate_limit()
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        resp = httpx.post(GITHUB_GRAPHQL, json=payload, headers=headers, timeout=30)
        self._update_rate_limit(resp)
        resp.raise_for_status()
        body = resp.json()
        if "errors" in body:
            if body.get("data"):
                # Partial failure — some aliases resolved, others didn't.
                # Log but return whatever data we got; callers already handle
                # missing aliases gracefully.
                logger.warning("GraphQL partial errors (returning data): {}", body["errors"])
                return body["data"]
            raise ValueError(f"GraphQL errors: {body['errors']}")
        return body["data"]

    @property
    def rate_limit_remaining(self) -> int:
        """Current GitHub API rate limit remaining (updated after each request)."""
        return self._rate_limit_remaining

    # -- rate-limit helpers ---------------------------------------------------

    def _wait_for_rate_limit(self) -> None:
        if self._rate_limit_remaining < 3:
            wait = max(self._rate_limit_reset - time.time(), 1)
            logger.info(
                "Rate limit low ({}). Waiting {:.0f}s...",
                self._rate_limit_remaining,
                wait,
            )
            time.sleep(wait + 1)

    def _update_rate_limit(self, resp: httpx.Response) -> None:
        remaining = resp.headers.get("x-ratelimit-remaining")
        reset = resp.headers.get("x-ratelimit-reset")
        if remaining is not None:
            self._rate_limit_remaining = int(remaining)
        if reset is not None:
            self._rate_limit_reset = float(reset)


def batch_fetch_commit_shas(
    client: GitHubClient,
    repos: list[tuple[str, str, str]],
) -> dict[str, str]:
    """Fetch latest commit SHAs for multiple repos via batched GraphQL queries.

    Each element of *repos* is ``(owner, repo_name, branch)``.

    Returns a dict mapping ``"owner/repo_name:branch"`` to the HEAD commit SHA.
    Repos that fail (private, deleted, empty) are silently omitted.
    """
    result: dict[str, str] = {}
    for chunk_start in range(0, len(repos), _GRAPHQL_BATCH_CHUNK):
        chunk = repos[chunk_start : chunk_start + _GRAPHQL_BATCH_CHUNK]
        aliases: list[str] = []
        alias_map: dict[str, str] = {}  # alias -> "owner/repo"
        for i, (owner, repo_name, branch) in enumerate(chunk):
            alias = f"r{i}"
            aliases.append(
                f'{alias}: repository(owner: "{owner}", name: "{repo_name}") {{'
                f'  ref(qualifiedName: "refs/heads/{branch}") {{'
                f"    target {{ oid }}"
                f"  }}"
                f"}}"
            )
            alias_map[alias] = f"{owner}/{repo_name}:{branch}"

        query = "query {\n" + "\n".join(aliases) + "\n}"

        try:
            data = client.graphql(query)
        except (httpx.HTTPStatusError, ValueError) as exc:
            logger.warning("GraphQL batch failed (chunk {}-{}): {}", chunk_start, chunk_start + len(chunk), exc)
            continue

        for alias, full_name in alias_map.items():
            repo_data = data.get(alias)
            if repo_data and repo_data.get("ref") and repo_data["ref"].get("target"):
                result[full_name] = repo_data["ref"]["target"]["oid"]

    return result
