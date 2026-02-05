"""Gemini LLM client for skill search."""

import httpx

_GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def create_gemini_client(api_key: str) -> dict:
    """Create a Gemini client configuration.

    Returns a dict containing the API key and base URL.
    We use a plain dict rather than a class to keep the interface simple.
    """
    return {
        "api_key": api_key,
        "base_url": _GEMINI_API_URL,
    }


def search_skills_with_llm(
    client: dict,
    query: str,
    index: str,
    model: str = "gemini-2.0-flash",
) -> str:
    """Search for skills using Gemini to match a query against the index.

    Sends the full skill index and user query to Gemini, asking it to
    rank and recommend the most relevant skills.

    Args:
        client: Gemini client config dict with api_key and base_url.
        query: User's natural language search query.
        index: JSONL string of the skill index.
        model: Gemini model to use.

    Returns:
        Gemini's response text with ranked skill recommendations.
    """
    system_prompt = (
        "You are a skill recommendation engine for Decision Hub, "
        "a package manager for AI agent skills. Given a user query and "
        "a skill index (JSONL format), recommend the most relevant skills. "
        "For each recommendation, include the skill reference (org/skill), "
        "version, trust grade, and a brief reason why it matches. "
        "Order by relevance. If no skills match, say so clearly."
    )

    user_message = (
        f"User query: {query}\n\n"
        f"Skill index:\n{index}"
    )

    url = f"{client['base_url']}/{model}:generateContent"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{system_prompt}\n\n{user_message}"}
                ]
            }
        ],
    }

    with httpx.Client(timeout=30) as http_client:
        resp = http_client.post(
            url,
            params={"key": client["api_key"]},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    # Extract text from the first candidate
    candidates = data.get("candidates", [])
    if not candidates:
        return "No recommendations found."

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        return "No recommendations found."

    return parts[0].get("text", "No recommendations found.")


def analyze_code_safety(
    client: dict,
    source_snippets: list[dict],
    skill_name: str,
    skill_description: str,
    model: str = "gemini-2.0-flash",
) -> list[dict]:
    """Ask Gemini to judge whether flagged code patterns are actually dangerous.

    A regex pre-scan finds suspicious patterns (subprocess, etc.). This function
    sends those findings plus the skill's stated purpose to the LLM so it can
    decide which findings are legitimate for the skill vs genuinely risky.

    Args:
        client: Gemini client config dict.
        source_snippets: List of dicts with keys 'file', 'label', 'line'
            describing each flagged pattern.
        skill_name: Name of the skill being scanned.
        skill_description: What the skill says it does.
        model: Gemini model to use.

    Returns:
        List of dicts with keys 'file', 'label', 'dangerous' (bool), 'reason'.
    """
    import json

    prompt = (
        "You are a security reviewer for Decision Hub, a package registry for "
        "AI agent skills. A regex pre-scan flagged the following code patterns "
        "as potentially dangerous. Your job is to decide whether each finding "
        "is genuinely dangerous or is legitimate given the skill's purpose.\n\n"
        f"Skill name: {skill_name}\n"
        f"Skill description: {skill_description}\n\n"
        "Flagged patterns:\n"
    )
    for s in source_snippets:
        prompt += f"- File: {s['file']}, Pattern: {s['label']}, Context: {s['line']}\n"

    prompt += (
        "\nFor each finding, respond with a JSON array. Each element must have:\n"
        '  {"file": "<filename>", "label": "<pattern label>", '
        '"dangerous": true/false, "reason": "<brief explanation>"}\n\n'
        "Only mark a finding as dangerous if it poses a real security risk "
        "given what this skill does. Subprocess calls for file packing, XML "
        "processing, or build tooling are typically legitimate. "
        "Respond ONLY with the JSON array, no other text."
    )

    url = f"{client['base_url']}/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.0},
    }

    with httpx.Client(timeout=30) as http_client:
        resp = http_client.post(
            url,
            params={"key": client["api_key"]},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    candidates = data.get("candidates", [])
    if not candidates:
        return [{"file": s["file"], "label": s["label"], "dangerous": True,
                 "reason": "LLM returned no response"} for s in source_snippets]

    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")

    # Strip markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        results = json.loads(text)
        if isinstance(results, list):
            return results
    except json.JSONDecodeError:
        pass

    # Fallback: treat everything as dangerous if we can't parse the response
    return [{"file": s["file"], "label": s["label"], "dangerous": True,
             "reason": "Could not parse LLM response"} for s in source_snippets]
