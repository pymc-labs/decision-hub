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

    Returns:
        A SkillIndexEntry with a computed trust score.
    """
    return SkillIndexEntry(
        org_slug=org_slug,
        skill_name=skill_name,
        description=description,
        latest_version=latest_version,
        eval_status=eval_status,
        trust_score=format_trust_score(eval_status),
        author=author,
        category=category,
    )


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


def format_deterministic_results(entries: list[SkillIndexEntry]) -> str:
    """Format pre-ranked entries as markdown when Gemini is unavailable.

    Used as a deterministic fallback when the LLM reranker fails.
    Returns a numbered markdown list with skill details.
    """
    if not entries:
        return "No skills matched your query."

    lines: list[str] = []
    for i, e in enumerate(entries, 1):
        trust = e.trust_score
        lines.append(f"{i}. **{e.org_slug}/{e.skill_name}** v{e.latest_version} [{trust}] — {e.description}")
    return "\n".join(lines)


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
        obj = {
            "org": entry.org_slug,
            "skill": entry.skill_name,
            "description": entry.description,
            "version": entry.latest_version,
            "eval_status": entry.eval_status,
            "trust": entry.trust_score,
            "author": entry.author,
            "category": entry.category,
        }
        lines.append(json.dumps(obj))
    return "\n".join(lines)
