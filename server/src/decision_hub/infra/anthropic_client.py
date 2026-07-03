"""Anthropic API client for LLM-based eval judging.

Uses httpx to call the Anthropic Messages API directly,
avoiding a heavy SDK dependency.
"""

import json
import time

import httpx
from loguru import logger

_ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
# Retry transient errors — 429 (rate limit), 529 (overloaded), 5xx.
# Bursty eval judgment loads regularly hit these and previously produced
# spurious verdict="error" rows that required manual re-runs.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}
_MAX_RETRIES = 3

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
        f"## Eval Case: {eval_case_name}\n\n## Criteria\n{eval_criteria}\n\n## Agent Output\n{truncated_output}"
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

    logger.debug("Calling Anthropic judge API model={} case={}", model, eval_case_name)
    data = _post_with_retry(payload, headers)

    # Filter to text blocks — responses may include non-text blocks like
    # tool_use or thinking that would raise on ["text"] indexing.
    raw_text = _first_text_block(data)
    if raw_text is None:
        logger.warning("Judge response has no text block for case={}", eval_case_name)
        return {"verdict": "error", "reasoning": "Judge returned no text content"}

    result = _parse_judge_response(raw_text)
    logger.debug("Judge verdict for '{}': {}", eval_case_name, result["verdict"])
    return result


def _post_with_retry(payload: dict, headers: dict) -> dict:
    """POST to Anthropic with retry on transient errors and Retry-After support."""
    for attempt in range(_MAX_RETRIES):
        response = httpx.post(
            _ANTHROPIC_API_URL,
            json=payload,
            headers=headers,
            timeout=60,
        )
        if response.status_code in _RETRYABLE_STATUS and attempt < _MAX_RETRIES - 1:
            retry_after = response.headers.get("retry-after")
            try:
                delay = float(retry_after) if retry_after else min(2.0 * (2**attempt), 30.0)
            except ValueError:
                delay = min(2.0 * (2**attempt), 30.0)
            logger.warning(
                "Anthropic returned {} (attempt {}/{}), retrying in {}s",
                response.status_code,
                attempt + 1,
                _MAX_RETRIES,
                delay,
            )
            time.sleep(delay)
            continue
        response.raise_for_status()
        return response.json()
    # Unreachable — the loop either returns or raises before falling through.
    raise RuntimeError("Anthropic retry loop exited without a response")


def _first_text_block(data: dict) -> str | None:
    """Return the text of the first `type=='text'` block, or None if absent."""
    for block in data.get("content", []):
        if block.get("type") == "text" and "text" in block:
            return block["text"]
    return None


def _parse_judge_response(raw_text: str) -> dict:
    """Parse the judge's JSON response, handling malformed output gracefully.

    Handles JSON wrapped in markdown code blocks (```json ... ```).
    """
    import re

    # Strip markdown code block wrappers if present
    cleaned = raw_text.strip()
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1).strip()

    try:
        result = json.loads(cleaned)
        verdict = result.get("verdict", "error")
        if verdict not in ("pass", "fail"):
            return {"verdict": "error", "reasoning": f"Invalid verdict: {verdict}. Raw: {raw_text}"}
        return {"verdict": verdict, "reasoning": result.get("reasoning", "")}
    except (json.JSONDecodeError, KeyError):
        logger.warning("Failed to parse judge response: {}", raw_text[:300])
        return {"verdict": "error", "reasoning": f"Failed to parse judge response: {raw_text[:500]}"}
