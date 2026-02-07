"""Shared parsing utilities for LLM response text."""

import json
import re


def strip_markdown_fences(text: str) -> str:
    """Remove markdown code-block fences from LLM output.

    Handles both ```json ... ``` and bare ``` ... ``` wrappers.
    Returns the inner text, stripped of leading/trailing whitespace.
    """
    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
    if match:
        return match.group(1).strip()
    return cleaned


def parse_json_or_fallback(
    text: str,
    fallback_items: list[dict],
    fallback_reason: str = "Could not parse LLM response",
) -> list[dict]:
    """Parse a JSON array from LLM text, falling back to a default on failure.

    Strips markdown fences first, then attempts JSON parsing. If the result
    is a valid list, returns it. Otherwise returns fallback_items with the
    given reason injected.
    """
    cleaned = strip_markdown_fences(text)
    try:
        results = json.loads(cleaned)
        if isinstance(results, list):
            return results
    except json.JSONDecodeError:
        pass

    return [{**item, "reason": fallback_reason} for item in fallback_items]
