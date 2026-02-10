"""Skill classification into predefined categories.

Uses a lightweight LLM call (Gemini Flash) after the gauntlet to assign
each skill a category and subcategory from a fixed taxonomy. The result
is stored on the skill record for filtering and search.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

# The full taxonomy: top-level group -> subcategories
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

# Flat list of all valid subcategories for validation
ALL_SUBCATEGORIES: frozenset[str] = frozenset(
    sub for subs in CATEGORY_TAXONOMY.values() for sub in subs
)

# Reverse lookup: subcategory -> top-level group
SUBCATEGORY_TO_GROUP: dict[str, str] = {
    sub: group
    for group, subs in CATEGORY_TAXONOMY.items()
    for sub in subs
}

DEFAULT_CATEGORY = "Other & Utilities"


@dataclass(frozen=True)
class SkillClassification:
    """Result of classifying a skill."""
    category: str       # subcategory, e.g. "Backend & APIs"
    group: str          # top-level group, e.g. "Development"
    confidence: float   # 0.0-1.0 from the LLM


# Type alias for the LLM classification callback.
# Accepts (skill_name, description, body) -> SkillClassification
ClassifyFn = Callable[[str, str, str], SkillClassification]


def build_taxonomy_prompt_fragment() -> str:
    """Build the taxonomy section of the classification prompt."""
    lines = []
    for group, subcategories in CATEGORY_TAXONOMY.items():
        lines.append(f"  {group}:")
        for sub in subcategories:
            lines.append(f"    - {sub}")
    return "\n".join(lines)


def parse_classification_response(text: str) -> SkillClassification:
    """Parse LLM JSON response into a SkillClassification.

    Expected format: {"category": "...", "confidence": 0.9}
    Falls back to DEFAULT_CATEGORY if the response is unparseable or
    the category isn't in the taxonomy.
    """
    import json

    text = text.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return SkillClassification(
            category=DEFAULT_CATEGORY,
            group=SUBCATEGORY_TO_GROUP[DEFAULT_CATEGORY],
            confidence=0.0,
        )

    category = data.get("category", DEFAULT_CATEGORY)
    confidence = float(data.get("confidence", 0.0))

    if category not in ALL_SUBCATEGORIES:
        category = DEFAULT_CATEGORY
        confidence = 0.0

    return SkillClassification(
        category=category,
        group=SUBCATEGORY_TO_GROUP[category],
        confidence=confidence,
    )
