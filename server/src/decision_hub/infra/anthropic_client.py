"""Anthropic API client for LLM-based eval judging.

Uses httpx to call the Anthropic Messages API directly,
avoiding a heavy SDK dependency.
"""

import json

import httpx
from loguru import logger

from decision_hub.infra.parsing import strip_markdown_fences

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

_JUDGE_SYSTEM_PROMPT = """You are an evaluation judge for AI agent skill tests.

You will be given:
1. The name of the eval case
2. PASS/FAIL criteria written by the skill author
3. The agent's output from running the eval

Your job is to determine whether the agent's output meets the criteria.

Respond with ONLY a JSON object (no markdown fences):
{"verdict": "pass" or "fail", "reasoning": "brief explanation"}
"""

_MAX_OUTPUT_CHARS = 10000


def judge_eval_output(
    api_key: str,
    model: str,
    eval_case_name: str,
    eval_criteria: str,
    agent_output: str,
) -> dict:
    """Judge agent output against eval criteria using an Anthropic model.

    Returns:
        Dict with keys "verdict" ("pass"|"fail"|"error") and "reasoning".
    """
    truncated_output = agent_output[:_MAX_OUTPUT_CHARS]
    if len(agent_output) > _MAX_OUTPUT_CHARS:
        truncated_output += "\n... [truncated]"

    user_message = (
        f"## Eval Case: {eval_case_name}\n\n"
        f"## Criteria\n{eval_criteria}\n\n"
        f"## Agent Output\n{truncated_output}"
    )

    payload = {
        "model": model,
        "max_tokens": 512,
        "system": _JUDGE_SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
    }

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    response = httpx.post(
        _ANTHROPIC_API_URL,
        json=payload,
        headers=headers,
        timeout=60,
    )
    response.raise_for_status()

    data = response.json()
    raw_text = data["content"][0]["text"]

    return _parse_judge_response(raw_text)


def _parse_judge_response(raw_text: str) -> dict:
    """Parse the judge's JSON response, handling malformed output gracefully.

    Handles JSON wrapped in markdown code blocks (```json ... ```).
    """
    cleaned = strip_markdown_fences(raw_text)

    try:
        result = json.loads(cleaned)
        verdict = result.get("verdict", "error")
        if verdict not in ("pass", "fail"):
            return {"verdict": "error", "reasoning": f"Invalid verdict: {verdict}. Raw: {raw_text}"}
        return {"verdict": verdict, "reasoning": result.get("reasoning", "")}
    except (json.JSONDecodeError, KeyError):
        return {"verdict": "error", "reasoning": f"Failed to parse judge response: {raw_text[:500]}"}
