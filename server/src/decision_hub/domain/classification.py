"""Skill classification domain logic — prompt building and response parsing.

Uses the taxonomy from dhub_core (single source of truth) to build classifier
prompts and parse LLM responses.
"""

import json

from dhub_core.taxonomy import (
    ALL_SUBCATEGORIES,
    CATEGORY_TAXONOMY,
    DEFAULT_CATEGORY,
    SUBCATEGORY_TO_GROUP,
    SkillClassification,
)


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

    if not isinstance(data, dict):
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
