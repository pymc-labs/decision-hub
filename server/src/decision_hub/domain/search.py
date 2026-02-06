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
) -> SkillIndexEntry:
    """Create a search index entry from skill metadata.

    Args:
        org_slug: Organisation slug.
        skill_name: Skill name.
        description: Skill description from SKILL.md.
        latest_version: Latest published version string.
        eval_status: Current evaluation status (pending/passed/failed).
        author: GitHub username of the publisher.

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
    )


def format_trust_score(eval_status: str) -> str:
    """Map an evaluation status to a human-readable trust grade.

    Grades:
    - passed  -> "A" (trusted, all checks passed)
    - pending -> "C" (unverified, awaiting evaluation)
    - failed  -> "F" (untrusted, checks failed)
    """
    scores = {
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
        obj = {
            "org": entry.org_slug,
            "skill": entry.skill_name,
            "description": entry.description,
            "version": entry.latest_version,
            "eval_status": entry.eval_status,
            "trust": entry.trust_score,
            "author": entry.author,
        }
        lines.append(json.dumps(obj))
    return "\n".join(lines)


