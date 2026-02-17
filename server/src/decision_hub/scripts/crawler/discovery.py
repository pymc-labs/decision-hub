"""GitHub discovery strategies for finding repos with SKILL.md files.

Five complementary strategies work around GitHub's Search API 1,000-result
limit. Each strategy returns dict[str, DiscoveredRepo] keyed by full_name.
The orchestrator merges with dict.update().
"""

import base64
import re
import time
from collections.abc import Generator

import httpx
from loguru import logger

from decision_hub.scripts.crawler.models import CrawlStats, DiscoveredRepo

GITHUB_API = "https://api.github.com"

# Organizations from major gen-AI companies and tool providers. Repos owned by
# these orgs are tagged as trusted and processed before community repos so the
# highest-signal skills are indexed first.
TRUSTED_ORGS: frozenset[str] = frozenset(
    {
        # Decision Hub
        "pymc-labs",
        # LLM providers
        "anthropics",
        "openai",
        "google",
        "google-gemini",
        "googleapis",
        "googlecloudplatform",
        "meta-llama",
        "mistralai",
        "cohere-ai",
        # AI-native dev tools
        "replit",
        "cursor",
        "getcursor",
        "codeium",
        "exafunction",
        "sourcegraph",
        "continuedev",
        "github",
        "microsoft",
        "aws",
        "vercel",
        # Agent / orchestration frameworks
        "langchain-ai",
        "run-llama",
        "huggingface",
        "deepmind",
        "google-deepmind",
        "stability-ai",
    }
)


_BARE_OWNER_REPO = re.compile(r"^[\w.-]+/[\w.-]+$")


def parse_repo_url(url: str) -> str:
    """Extract 'owner/repo' from various GitHub URL formats.

    Supports:
        owner/repo
        https://github.com/owner/repo
        https://github.com/owner/repo.git
        git@github.com:owner/repo.git

    Delegates SSH/HTTPS parsing to :func:`decision_hub.domain.tracker.parse_github_repo_url`
    and adds bare ``owner/repo`` support on top.
    """
    from decision_hub.domain.tracker import parse_github_repo_url

    # Bare owner/repo — check first since it's not a URL
    if _BARE_OWNER_REPO.match(url):
        return url

    try:
        owner, repo = parse_github_repo_url(url)
        return f"{owner}/{repo}"
    except ValueError:
        msg = f"Cannot parse GitHub repo from: {url}"
        raise ValueError(msg) from None


def resolve_repos(
    gh: "GitHubClient",
    repo_identifiers: list[str],
    stats: CrawlStats,
) -> dict[str, DiscoveredRepo]:
    """Resolve a list of repo identifiers to DiscoveredRepo objects via the GitHub API."""
    repos: dict[str, DiscoveredRepo] = {}
    for raw in repo_identifiers:
        try:
            full_name = parse_repo_url(raw)
        except ValueError:
            logger.error("Skipping invalid repo identifier: {}", raw)
            stats.errors.append(f"Invalid repo identifier: {raw}")
            continue

        resp = gh.get(f"/repos/{full_name}")
        stats.queries_made += 1
        if resp.status_code != 200:
            logger.error("Could not fetch repo {}: HTTP {}", full_name, resp.status_code)
            stats.errors.append(f"HTTP {resp.status_code} for {full_name}")
            continue

        d = resp.json()
        repos[full_name] = DiscoveredRepo(
            full_name=full_name,
            owner_login=d["owner"]["login"],
            owner_type=d["owner"]["type"],
            clone_url=d["clone_url"],
            stars=d.get("stargazers_count", 0),
            description=d.get("description") or "",
        )
        logger.info("Resolved repo: {} ({}★)", full_name, repos[full_name].stars)

    tag_trusted_repos(repos)
    return repos


def tag_trusted_repos(repos: dict[str, DiscoveredRepo]) -> None:
    """Mark repos whose owner is in TRUSTED_ORGS (case-insensitive, in-place)."""
    for repo in repos.values():
        if repo.owner_login.lower() in TRUSTED_ORGS:
            repo.is_trusted = True


# ---------------------------------------------------------------------------
# Strategy 0: Trusted org fast-path (runs before other strategies)
# ---------------------------------------------------------------------------


def search_trusted_orgs(gh: "GitHubClient", stats: CrawlStats) -> Generator[dict[str, DiscoveredRepo], None, None]:
    """Directly search for SKILL.md in each trusted org.

    One API call per org — much faster than waiting for generic strategies
    to stumble across trusted repos. Yields one batch per org.
    """
    for org in sorted(TRUSTED_ORGS):
        query = f"filename:SKILL.md org:{org}"
        found = _run_code_search(gh, query, stats)
        # Mark all as trusted since they come from known orgs
        for repo in found.values():
            repo.is_trusted = True
        if found:
            logger.info("Trusted org '{}': {} repos", org, len(found))
            yield found


# ---------------------------------------------------------------------------
# Strategy 1: File-size partitioning
# ---------------------------------------------------------------------------

SIZE_RANGES: list[tuple[int, int | None]] = [
    (0, 500),
    (501, 1000),
    (1001, 2000),
    (2001, 5000),
    (5001, 10000),
    (10001, 50000),
    (50001, None),
]


def search_by_file_size(gh: "GitHubClient", stats: CrawlStats) -> Generator[dict[str, DiscoveredRepo], None, None]:
    """Split filename:SKILL.md into non-overlapping byte-size ranges.

    Yields one batch per size range so the caller can start processing
    immediately instead of waiting for all ranges to complete.
    """
    total = 0
    for lo, hi in SIZE_RANGES:
        size_q = f"size:>={lo}" if hi is None else f"size:{lo}..{hi}"
        query = f"filename:SKILL.md {size_q}"
        found = _run_code_search(gh, query, stats)
        total += len(found)
        logger.info("Size {}: +{} (total {})", size_q, len(found), total)
        if found:
            yield found


# ---------------------------------------------------------------------------
# Strategy 2: Path-based search
# ---------------------------------------------------------------------------

SKILL_PATHS = ["skills", ".claude", ".codex", ".github", "agent-skills"]


def search_by_path(gh: "GitHubClient", stats: CrawlStats) -> Generator[dict[str, DiscoveredRepo], None, None]:
    """Target common skill paths where SKILL.md files are typically found.

    Yields one batch per path so processing can start immediately.
    """
    total = 0
    for skill_path in SKILL_PATHS:
        query = f"filename:SKILL.md path:{skill_path}"
        found = _run_code_search(gh, query, stats)
        total += len(found)
        logger.info("Path '{}': +{} (total {})", skill_path, len(found), total)
        if found:
            yield found


# ---------------------------------------------------------------------------
# Strategy 3: Topic-based discovery
# ---------------------------------------------------------------------------

SKILL_TOPICS = [
    "agent-skills",
    "claude-skills",
    "ai-agent-skills",
    "claude-code-skills",
    "codex-skills",
    "copilot-skills",
    "cursor-skills",
    "windsurf-skills",
]


def search_by_topic(gh: "GitHubClient", stats: CrawlStats) -> Generator[dict[str, DiscoveredRepo], None, None]:
    """Search repos by GitHub topics, paginating up to 5 pages per topic.

    Yields one batch per topic so processing can start immediately.
    """
    for topic in SKILL_TOPICS:
        batch: dict[str, DiscoveredRepo] = {}
        page = 1
        while page <= 5:
            resp = gh.get(
                "/search/repositories",
                params={
                    "q": f"topic:{topic}",
                    "sort": "stars",
                    "order": "desc",
                    "per_page": 100,
                    "page": page,
                },
            )
            stats.queries_made += 1
            if resp.status_code != 200:
                break
            items = resp.json().get("items", [])
            if not items:
                break
            for item in items:
                fn = item["full_name"]
                if fn not in batch:
                    batch[fn] = DiscoveredRepo(
                        full_name=fn,
                        owner_login=item["owner"]["login"],
                        owner_type=item["owner"]["type"],
                        clone_url=item["clone_url"],
                        stars=item.get("stargazers_count", 0),
                        description=item.get("description") or "",
                    )
            if len(items) < 100:
                break
            page += 1
            time.sleep(1)
        logger.info("Topic '{}': {}", topic, len(batch))
        if batch:
            yield batch


# ---------------------------------------------------------------------------
# Strategy 4: Fork scanning
# ---------------------------------------------------------------------------


def scan_forks(
    gh: "GitHubClient",
    popular_repos: list[str],
    stats: CrawlStats,
) -> Generator[dict[str, DiscoveredRepo], None, None]:
    """Enumerate forks of the top most-starred discovered repos.

    Yields one batch per source repo so processing can start immediately.
    """
    for repo_name in popular_repos:
        batch: dict[str, DiscoveredRepo] = {}
        page = 1
        while page <= 3:
            resp = gh.get(
                f"/repos/{repo_name}/forks",
                params={"sort": "stargazers", "per_page": 100, "page": page},
            )
            stats.queries_made += 1
            if resp.status_code != 200:
                break
            forks = resp.json()
            if not forks:
                break
            for fork in forks:
                fn = fork["full_name"]
                if fn not in batch:
                    batch[fn] = DiscoveredRepo(
                        full_name=fn,
                        owner_login=fork["owner"]["login"],
                        owner_type=fork["owner"]["type"],
                        clone_url=fork["clone_url"],
                        stars=fork.get("stargazers_count", 0),
                        description=fork.get("description") or "",
                    )
            if len(forks) < 100:
                break
            page += 1
        logger.info("Forks of '{}': {}", repo_name, len(batch))
        if batch:
            yield batch


# ---------------------------------------------------------------------------
# Strategy 5: Curated list parsing
# ---------------------------------------------------------------------------

CURATED_LIST_REPOS = [
    "skillmatic-ai/awesome-agent-skills",
    "hoodini/ai-agents-skills",
    "CommandCodeAI/agent-skills",
    "heilcheng/awesome-agent-skills",
]


def parse_curated_lists(gh: "GitHubClient", stats: CrawlStats) -> Generator[dict[str, DiscoveredRepo], None, None]:
    """Parse READMEs from known awesome-lists for GitHub repo links.

    Yields one batch per curated list so processing can start immediately.
    """
    link_re = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+)")
    seen_refs: set[str] = set()  # dedup across curated lists
    for list_repo in CURATED_LIST_REPOS:
        resp = gh.get(f"/repos/{list_repo}/readme")
        stats.queries_made += 1
        if resp.status_code != 200:
            continue
        try:
            content = base64.b64decode(resp.json().get("content", "")).decode()
        except Exception:
            continue
        refs = {
            m.rstrip("/").removesuffix(".git")
            for m in link_re.findall(content)
            if m.rstrip("/").removesuffix(".git").count("/") == 1
        }
        batch: dict[str, DiscoveredRepo] = {}
        for ref in refs:
            if ref in seen_refs:
                continue
            seen_refs.add(ref)
            dr = gh.get(f"/repos/{ref}")
            stats.queries_made += 1
            if dr.status_code != 200:
                continue
            d = dr.json()
            batch[ref] = DiscoveredRepo(
                full_name=ref,
                owner_login=d["owner"]["login"],
                owner_type=d["owner"]["type"],
                clone_url=d["clone_url"],
                stars=d.get("stargazers_count", 0),
                description=d.get("description") or "",
            )
        logger.info("Curated '{}': {} refs", list_repo, len(refs))
        if batch:
            yield batch


# ---------------------------------------------------------------------------
# Shared code search helper
# ---------------------------------------------------------------------------


def _run_code_search(
    gh: "GitHubClient",
    query: str,
    stats: CrawlStats,
) -> dict[str, DiscoveredRepo]:
    """Paginated code search (up to 10 pages, 100 items each)."""
    repos: dict[str, DiscoveredRepo] = {}
    page = 1
    while page <= 10:
        resp = gh.get(
            "/search/code",
            params={"q": query, "per_page": 100, "page": page},
        )
        stats.queries_made += 1
        if resp.status_code in (422, 403):
            break
        if resp.status_code != 200:
            break
        items = resp.json().get("items", [])
        if not items:
            break
        for item in items:
            repo = item.get("repository", {})
            fn = repo.get("full_name", "")
            if fn and fn not in repos:
                repos[fn] = DiscoveredRepo(
                    full_name=fn,
                    owner_login=repo["owner"]["login"],
                    owner_type=repo["owner"].get("type", "User"),
                    clone_url=repo.get("clone_url", f"https://github.com/{fn}.git"),
                    stars=repo.get("stargazers_count", 0),
                    description=repo.get("description") or "",
                )
        if len(items) < 100:
            break
        page += 1
        time.sleep(2)
    return repos


# ---------------------------------------------------------------------------
# GitHub API client with rate-limit tracking
# ---------------------------------------------------------------------------


class GitHubClient:
    """Rate-limit-aware HTTP client for the GitHub API."""

    def __init__(self, token: str | None = None):
        headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=GITHUB_API,
            headers=headers,
            timeout=30,
        )
        self._rate_limit_remaining = 999
        self._rate_limit_reset = 0.0

    def close(self) -> None:
        self._client.close()

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
