"""Skill category taxonomy — single source of truth.

Defines the category hierarchy used by the Gemini classifier, the search API,
the CLI, and the frontend. Any taxonomy changes should be made here only.
"""

from dataclasses import dataclass

CATEGORY_TAXONOMY: dict[str, list[str]] = {
    "Development": [
        "Backend & APIs",
        "Frontend & UI",
        "Mobile Development",
        "Programming Languages",
    ],
    "AI & Automation": [
        "AI & LLM",
        "Agents & Orchestration",
        "Prompts & Instructions",
    ],
    "Data & Documents": [
        "Data & Database",
        "Documents & Files",
    ],
    "DevOps & Security": [
        "DevOps & Cloud",
        "Git & Version Control",
        "Testing & QA",
        "Security & Auth",
    ],
    "Business & Productivity": [
        "Productivity & Notes",
        "Business & Finance",
        "Social & Communications",
        "Content & Writing",
    ],
    "Media & IoT": [
        "Multimedia & Audio/Video",
        "Smart Home & IoT",
    ],
    "Specialized": [
        "Data Science & Statistics",
        "Other Science & Mathematics",
        "Blockchain & Web3",
        "MCP & Skills",
        "Other & Utilities",
    ],
}

ALL_SUBCATEGORIES: frozenset[str] = frozenset(sub for subs in CATEGORY_TAXONOMY.values() for sub in subs)

SUBCATEGORY_TO_GROUP: dict[str, str] = {sub: group for group, subs in CATEGORY_TAXONOMY.items() for sub in subs}

DEFAULT_CATEGORY = "Other & Utilities"


@dataclass(frozen=True)
class SkillClassification:
    """Result of classifying a skill."""

    category: str  # subcategory, e.g. "Backend & APIs"
    group: str  # top-level group, e.g. "Development"
    confidence: float  # 0.0-1.0 from the LLM
