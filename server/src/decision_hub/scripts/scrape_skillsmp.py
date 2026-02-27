"""Scrape GitHub repository URLs from SkillsMP.com for a given category.

Uses the SkillsMP REST API to search for skills and extract their GitHub
repo URLs. Results are deduplicated by repo and saved to a JSON file that
can be fed directly to the crawler via ``--repos-file``.

Usage:
    # Scrape the Data & AI category
    cd server && uv run --package decision-hub-server \
      python -m decision_hub.scripts.scrape_skillsmp \
      --api-key sk_live_skillsmp_xxx \
      --category data-ai \
      --output skillsmp_data_ai.json

    # Then publish via crawler
    cd server && DHUB_ENV=dev uv run --package decision-hub-server \
      python -m decision_hub.scripts.github_crawler \
      --repos-file skillsmp_data_ai.json \
      --github-token "$(gh auth token)"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

SKILLSMP_API = "https://skillsmp.com/api/v1"

# Search queries that cover the "Data & AI" category well.
# The SkillsMP API only supports keyword search — no category filter — so we
# use multiple domain-specific queries and deduplicate the results.
DATA_AI_QUERIES: dict[str, list[str]] = {
    "data-ai": [
        "data science",
        "machine learning",
        "data analysis",
        "data engineering",
        "deep learning",
        "natural language processing",
        "computer vision",
        "data pipeline",
        "LLM",
        "pandas",
        "pytorch",
        "tensorflow",
        "scikit-learn",
        "data visualization",
        "AI model",
        "neural network",
        "NLP",
        "MLOps",
        "embeddings",
        "vector database",
    ],
    # Easy to add other categories later
    "development": [
        "developer tools",
        "code generation",
        "refactoring",
        "debugging",
        "testing",
        "CI/CD",
        "git",
        "code review",
    ],
}

_GITHUB_URL_RE = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?/?$")


@dataclass
class ScrapedSkill:
    """A skill discovered from SkillsMP."""

    full_name: str  # owner/repo
    github_url: str
    skill_name: str = ""
    author: str = ""
    description: str = ""
    stars: int = 0
    matched_query: str = ""


@dataclass
class ScrapeResult:
    """Container for all scraped results."""

    source: str = "skillsmp.com"
    category: str = ""
    scraped_at: str = ""
    total_api_calls: int = 0
    repos: list[ScrapedSkill] = field(default_factory=list)


def _extract_repo_fullname(github_url: str) -> str | None:
    """Extract 'owner/repo' from a GitHub URL."""
    m = _GITHUB_URL_RE.match(github_url.rstrip("/"))
    if m:
        return m.group(1)
    return None


def _search_skills(
    client: httpx.Client,
    query: str,
    *,
    max_pages: int = 5,
    limit: int = 20,
    sort_by: str = "stars",
) -> tuple[list[dict], int]:
    """Search SkillsMP for skills matching a query. Returns (skills, api_calls)."""
    skills: list[dict] = []
    api_calls = 0

    for page in range(1, max_pages + 1):
        resp = client.get(
            f"{SKILLSMP_API}/skills/search",
            params={"q": query, "page": page, "limit": limit, "sortBy": sort_by},
        )
        api_calls += 1

        if resp.status_code == 429:
            print(f"  Rate limited on query '{query}' page {page}. Stopping pagination.", flush=True)
            break

        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code} for query '{query}' page {page}", flush=True)
            break

        data = resp.json()
        page_skills = data.get("skills", data.get("results", []))
        if not page_skills:
            break

        skills.extend(page_skills)

        # Stop if we've fetched all pages
        has_next = data.get("hasNext", data.get("has_next", False))
        total_pages = data.get("totalPages", data.get("total_pages"))
        if not has_next or (total_pages and page >= total_pages):
            break

        # Polite pause between pages
        time.sleep(0.3)

    return skills, api_calls


def scrape_category(
    api_key: str,
    category: str,
    *,
    max_pages_per_query: int = 5,
    queries: list[str] | None = None,
) -> ScrapeResult:
    """Scrape all skills for a category using the SkillsMP search API."""
    if queries is None:
        queries = DATA_AI_QUERIES.get(category)
        if queries is None:
            print(f"No predefined queries for category '{category}'.")
            print(f"Available categories: {', '.join(DATA_AI_QUERIES)}")
            print("Use --queries to provide custom search terms.")
            sys.exit(1)

    result = ScrapeResult(
        category=category,
        scraped_at=datetime.now(UTC).isoformat(),
    )

    seen_repos: dict[str, ScrapedSkill] = {}  # full_name -> skill (dedup)

    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(headers=headers, timeout=30) as client:
        for i, query in enumerate(queries, 1):
            print(f"[{i}/{len(queries)}] Searching: '{query}'", flush=True)

            skills, api_calls = _search_skills(
                client,
                query,
                max_pages=max_pages_per_query,
            )
            result.total_api_calls += api_calls

            new_count = 0
            for skill in skills:
                github_url = skill.get("githubUrl", skill.get("github_url", ""))
                if not github_url:
                    continue

                full_name = _extract_repo_fullname(github_url)
                if not full_name:
                    continue

                if full_name not in seen_repos:
                    seen_repos[full_name] = ScrapedSkill(
                        full_name=full_name,
                        github_url=github_url,
                        skill_name=skill.get("name", ""),
                        author=skill.get("author", ""),
                        description=skill.get("description", ""),
                        stars=skill.get("stars", 0),
                        matched_query=query,
                    )
                    new_count += 1

            print(f"  Found {len(skills)} skills, {new_count} new repos (total: {len(seen_repos)})", flush=True)

            # Polite pause between queries
            time.sleep(0.5)

    # Sort by stars descending
    result.repos = sorted(seen_repos.values(), key=lambda s: s.stars, reverse=True)
    return result


def save_result(result: ScrapeResult, output_path: Path) -> None:
    """Save scrape results to a JSON file."""
    data = {
        "source": result.source,
        "category": result.category,
        "scraped_at": result.scraped_at,
        "total_api_calls": result.total_api_calls,
        "total_repos": len(result.repos),
        "repos": [asdict(r) for r in result.repos],
    }
    output_path.write_text(json.dumps(data, indent=2))
    print(f"\nSaved {len(result.repos)} repos to {output_path}")


def load_repos_file(path: Path) -> list[str]:
    """Load repo full_names from a scrape result JSON file.

    Returns a list of 'owner/repo' strings suitable for the crawler's --repos flag.
    """
    data = json.loads(path.read_text())
    repos = data.get("repos", [])
    return [r["full_name"] for r in repos if r.get("full_name")]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape GitHub repos from SkillsMP.com categories.",
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="SkillsMP API key (starts with sk_live_skillsmp_)",
    )
    parser.add_argument(
        "--category",
        default="data-ai",
        help="Category slug to scrape (default: data-ai)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON file path (default: skillsmp_{category}.json)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5,
        help="Max pages to fetch per search query (default: 5)",
    )
    parser.add_argument(
        "--queries",
        nargs="+",
        default=None,
        help="Custom search queries (overrides built-in queries for the category)",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()

    output_path = args.output or Path(f"skillsmp_{args.category}.json")

    print(f"Scraping SkillsMP category: {args.category}")
    print(f"Max pages per query: {args.max_pages}")

    result = scrape_category(
        api_key=args.api_key,
        category=args.category,
        max_pages_per_query=args.max_pages,
        queries=args.queries,
    )

    save_result(result, output_path)

    print("\n--- Scrape Summary ---")
    print(f"Category:    {result.category}")
    print(f"API calls:   {result.total_api_calls}")
    print(f"Repos found: {len(result.repos)}")
    if result.repos:
        print("\nTop 10 repos by stars:")
        for r in result.repos[:10]:
            print(f"  {r.full_name} ({r.stars}★) — {r.skill_name}")

    print("\nTo publish via crawler:")
    print("  cd server && DHUB_ENV=dev uv run --package decision-hub-server \\")
    print("    python -m decision_hub.scripts.github_crawler \\")
    print(f"    --repos-file {output_path} \\")
    print('    --github-token "$(gh auth token)"')


if __name__ == "__main__":
    main()
