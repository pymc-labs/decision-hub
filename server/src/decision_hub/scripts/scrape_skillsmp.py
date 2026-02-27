"""Scrape GitHub repository URLs from SkillsMP.com by exact category.

Uses the SkillsMP category browsing endpoint to fetch all skills in a given
category. Results are deduplicated by repo and saved to a JSON file that
can be fed directly to the crawler via ``--repos-file``.

Usage:
    # Scrape a single category
    cd server && uv run --package decision-hub-server \
      python -m decision_hub.scripts.scrape_skillsmp \
      --categories data-engineering \
      --output skillsmp_data_engineering.json

    # Scrape multiple categories into one file
    cd server && uv run --package decision-hub-server \
      python -m decision_hub.scripts.scrape_skillsmp \
      --categories data-engineering data-analysis scientific-computing

    # Then publish via crawler
    cd server && DHUB_ENV=dev uv run --package decision-hub-server \
      python -m decision_hub.scripts.github_crawler \
      --repos-file skillsmp_data_engineering.json \
      --github-token "$(gh auth token)"
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

SKILLSMP_BASE = "https://skillsmp.com"

# GitHub URL → owner/repo extraction. Handles tree URLs like
# https://github.com/owner/repo/tree/main/path/to/skill
_GITHUB_REPO_RE = re.compile(r"https?://github\.com/([\w.-]+/[\w.-]+?)(?:\.git|/tree/.*)?/?$")

# Categories we care about for import.
TARGET_CATEGORIES = [
    "data-engineering",
    "data-analysis",
    "machine-learning",
    "scientific-computing",
    "architecture-patterns",
]

PAGE_LIMIT = 100  # max items per page (API cap)


@dataclass
class ScrapedSkill:
    """A skill discovered from SkillsMP."""

    full_name: str  # owner/repo
    github_url: str
    skill_name: str = ""
    author: str = ""
    description: str = ""
    stars: int = 0
    category: str = ""


@dataclass
class ScrapeResult:
    """Container for all scraped results."""

    source: str = "skillsmp.com"
    categories: list[str] = field(default_factory=list)
    scraped_at: str = ""
    total_api_calls: int = 0
    repos: list[ScrapedSkill] = field(default_factory=list)


def _extract_repo_fullname(github_url: str) -> str | None:
    """Extract 'owner/repo' from a GitHub URL (including /tree/... paths)."""
    m = _GITHUB_REPO_RE.match(github_url.rstrip("/"))
    if m:
        return m.group(1)
    return None


def _fetch_category(
    client: httpx.Client,
    category: str,
    *,
    max_pages: int = 50,
) -> tuple[list[dict], int]:
    """Fetch all skills in a category via the browse endpoint.

    Returns (skills, api_call_count).
    """
    skills: list[dict] = []
    api_calls = 0

    for page in range(1, max_pages + 1):
        resp = client.get(
            f"{SKILLSMP_BASE}/api/skills",
            params={
                "category": category,
                "page": page,
                "limit": PAGE_LIMIT,
                "sortBy": "stars",
            },
        )
        api_calls += 1

        if resp.status_code == 429:
            print(f"  Rate limited on page {page}. Stopping.", flush=True)
            break

        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code} on page {page}", flush=True)
            break

        data = resp.json()
        page_skills = data.get("skills", [])
        if not page_skills:
            break

        skills.extend(page_skills)

        pagination = data.get("pagination", {})
        if not pagination.get("hasNext", False):
            break

        # Polite pause between pages
        time.sleep(0.3)

    return skills, api_calls


def scrape_categories(
    categories: list[str],
    *,
    max_pages: int = 50,
) -> ScrapeResult:
    """Scrape all skills for the given categories, deduplicating by repo."""
    result = ScrapeResult(
        categories=categories,
        scraped_at=datetime.now(UTC).isoformat(),
    )

    seen_repos: dict[str, ScrapedSkill] = {}  # full_name -> skill (dedup)

    with httpx.Client(timeout=30) as client:
        for i, category in enumerate(categories, 1):
            print(f"[{i}/{len(categories)}] Fetching category: {category}", flush=True)

            skills, api_calls = _fetch_category(
                client,
                category,
                max_pages=max_pages,
            )
            result.total_api_calls += api_calls

            new_count = 0
            for skill in skills:
                github_url = skill.get("githubUrl", "")
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
                        category=category,
                    )
                    new_count += 1

            print(
                f"  Found {len(skills)} skills, {new_count} new repos (total unique: {len(seen_repos)})",
                flush=True,
            )

            # Polite pause between categories
            if i < len(categories):
                time.sleep(0.5)

    # Sort by stars descending
    result.repos = sorted(seen_repos.values(), key=lambda s: s.stars, reverse=True)
    return result


def save_result(result: ScrapeResult, output_path: Path) -> None:
    """Save scrape results to a JSON file."""
    data = {
        "source": result.source,
        "categories": result.categories,
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
        description="Scrape GitHub repos from SkillsMP.com by exact category.",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=TARGET_CATEGORIES,
        metavar="SLUG",
        help=(
            "Category slugs to scrape (default: all target categories). "
            "Use slugs from https://skillsmp.com/en/categories"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON file path (default: skillsmp_{first_category}.json)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help="Max pages to fetch per category (default: 50, 100 items/page)",
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()

    output_path = args.output or Path(f"skillsmp_{args.categories[0]}.json")

    print(f"Scraping SkillsMP categories: {', '.join(args.categories)}")
    print(f"Max pages per category: {args.max_pages}")

    result = scrape_categories(
        categories=args.categories,
        max_pages=args.max_pages,
    )

    save_result(result, output_path)

    print("\n--- Scrape Summary ---")
    print(f"Categories:  {', '.join(result.categories)}")
    print(f"API calls:   {result.total_api_calls}")
    print(f"Repos found: {len(result.repos)}")
    if result.repos:
        print("\nTop 10 repos by stars:")
        for r in result.repos[:10]:
            print(f"  {r.full_name} ({r.stars}★) — {r.skill_name} [{r.category}]")

    print("\nTo publish via crawler:")
    print("  cd server && DHUB_ENV=dev uv run --package decision-hub-server \\")
    print("    python -m decision_hub.scripts.github_crawler \\")
    print(f"    --repos-file {output_path} \\")
    print('    --github-token "$(gh auth token)"')


if __name__ == "__main__":
    main()
