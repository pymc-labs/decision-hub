"""Search index building and trust score formatting."""

import json

from decision_hub.models import SkillIndexEntry


def build_index_entry(
    org_slug: str,
    skill_name: str,
    description: str,
    latest_version: str,
    eval_status: str,
    author: str = "",
    category: str = "",
    download_count: int = 0,
    source_repo_url: str | None = None,
    gauntlet_summary: str | None = None,
    github_stars: int | None = None,
    github_forks: int | None = None,
    github_license: str | None = None,
    source_repo_removed: bool = False,
    github_is_archived: bool | None = None,
) -> SkillIndexEntry:
    """Create a search index entry from skill metadata.

    Args:
        org_slug: Organisation slug.
        skill_name: Skill name.
        description: Skill description from SKILL.md.
        latest_version: Latest published version string.
        eval_status: Current evaluation status (pending/passed/failed).
        author: GitHub username of the publisher.
        category: Skill category from LLM classification.
        download_count: Number of times the skill has been downloaded.
        source_repo_url: URL of the source GitHub repository.
        gauntlet_summary: Brief summary of non-pass gauntlet findings.
        github_stars: Number of GitHub stars on the source repository.
        github_forks: Number of GitHub forks on the source repository.
        github_license: SPDX license identifier from the source repository.
        source_repo_removed: Whether the source repo has been removed.
        github_is_archived: Whether the source repo is archived on GitHub.

    Returns:
        A SkillIndexEntry with a computed trust score.
    """
    source_status = "removed" if source_repo_removed else "archived" if github_is_archived else "active"
    return SkillIndexEntry(
        org_slug=org_slug,
        skill_name=skill_name,
        description=description,
        latest_version=latest_version,
        eval_status=eval_status,
        trust_score=format_trust_score(eval_status),
        author=author,
        category=category,
        download_count=download_count,
        source_repo_url=source_repo_url,
        gauntlet_summary=gauntlet_summary,
        github_stars=github_stars,
        github_forks=github_forks,
        github_license=github_license,
        source_status=source_status,
    )


def resolve_author_display(published_by: str) -> str:
    """Return a human-friendly author label.

    Tracker-published versions store ``tracker:<uuid>`` — display as "auto-sync".
    """
    if published_by.startswith("tracker:"):
        return "auto-sync"
    return published_by


def format_trust_score(eval_status: str) -> str:
    """Map an evaluation status to a human-readable trust grade.

    Handles both new A/B/C/F grades and legacy passed/pending/failed values.
    """
    scores = {
        "A": "A",
        "B": "B",
        "C": "C",
        "F": "F",
        "passed": "A",
        "pending": "C",
        "failed": "F",
    }
    return scores.get(eval_status, "?")


def serialize_index(entries: list[SkillIndexEntry]) -> str:
    """Serialize index entries to a JSONL string.

    Each line is a JSON object representing one skill index entry.

    Args:
        entries: List of SkillIndexEntry objects.

    Returns:
        A JSONL string with one entry per line.
    """
    lines = []
    for entry in entries:
        obj: dict = {
            "org": entry.org_slug,
            "skill": entry.skill_name,
            "description": entry.description,
            "version": entry.latest_version,
            "eval_status": entry.eval_status,
            "trust": entry.trust_score,
            "author": entry.author,
            "category": entry.category,
            "downloads": entry.download_count,
        }
        if entry.source_status != "active":
            obj["source_status"] = entry.source_status
        if entry.source_repo_url:
            obj["source_repo_url"] = entry.source_repo_url
        if entry.gauntlet_summary:
            obj["safety_notes"] = entry.gauntlet_summary
        if entry.github_stars is not None:
            obj["github_stars"] = entry.github_stars
        if entry.github_forks is not None:
            obj["github_forks"] = entry.github_forks
        if entry.github_license:
            obj["license"] = entry.github_license
        lines.append(json.dumps(obj))
    return "\n".join(lines)
