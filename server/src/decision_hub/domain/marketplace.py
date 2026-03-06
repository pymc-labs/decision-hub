"""Skill-to-Claude-plugin mapping and marketplace.json generation.

Transforms Decision Hub skill metadata into Claude Code plugin format.
SKILL.md is already Claude's native skill format — only the wrapping
metadata (plugin.json, marketplace.json) needs to be generated.
"""

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class SkillPluginEntry:
    """Skill metadata needed to generate a Claude plugin entry."""

    org_slug: str
    skill_name: str
    version: str
    description: str
    category: str
    gauntlet_grade: str  # A/B/C — F is excluded upstream
    eval_status: str  # passed/failed/pending/error
    download_count: int
    source_repo_url: str | None = None


def plugin_name_from_skill(org_slug: str, skill_name: str) -> str:
    """Build Claude plugin name from org and skill.

    Uses double-dash separator since both org and skill can contain
    single hyphens (e.g. pymc-labs--bayesian-modeling).
    """
    return f"{org_slug}--{skill_name}"


def _keywords(category: str, grade: str, eval_status: str) -> list[str]:
    """Build keyword list for plugin.json."""
    kw: list[str] = []
    if category:
        kw.append(category)
    kw.append(f"safety-grade-{grade}")
    if eval_status == "passed":
        kw.append("evals-passing")
    return kw


def build_plugin_json(
    *,
    org_slug: str,
    skill_name: str,
    version: str,
    description: str,
    source_repo_url: str | None,
    category: str,
    gauntlet_grade: str,
    eval_status: str,
) -> str:
    """Generate plugin.json content for a single skill.

    Returns JSON string ready to write as .claude-plugin/plugin.json.
    """
    data: dict = {
        "name": plugin_name_from_skill(org_slug, skill_name),
        "version": version,
        "description": description,
        "author": {"name": org_slug},
        "keywords": _keywords(category, gauntlet_grade, eval_status),
    }
    if source_repo_url:
        data["repository"] = source_repo_url
    return json.dumps(data, indent=2)


def _tags(grade: str, eval_status: str, download_count: int) -> list[str]:
    """Build tag list for marketplace.json entry."""
    tags = [f"safety-{grade}"]
    if eval_status == "passed":
        tags.append("evals-passing")
    tags.append(f"downloads-{download_count}")
    return tags


def build_marketplace_json(entries: list[SkillPluginEntry]) -> str:
    """Generate marketplace.json for all plugin entries.

    Returns JSON string conforming to Claude Code's marketplace schema.
    """
    plugins = []
    for e in entries:
        name = plugin_name_from_skill(e.org_slug, e.skill_name)
        plugins.append(
            {
                "name": name,
                "source": f"./plugins/{name}",
                "description": e.description,
                "version": e.version,
                "category": e.category or "uncategorized",
                "tags": _tags(e.gauntlet_grade, e.eval_status, e.download_count),
            }
        )

    marketplace = {
        "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
        "name": "decision-hub",
        "description": (
            "AI skills marketplace with safety guarantees and automated evals. "
            "Published via Decision Hub (hub.decision.ai)."
        ),
        "owner": {
            "name": "Decision Hub",
            "email": "support@decision.ai",
        },
        "metadata": {
            "version": "1.0.0",
            "pluginRoot": "./plugins",
        },
        "plugins": plugins,
    }
    return json.dumps(marketplace, indent=2)
