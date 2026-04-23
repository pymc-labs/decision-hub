"""Anthropic API client for LLM-based eval judging.

Uses httpx to call the Anthropic Messages API directly,
avoiding a heavy SDK dependency.
"""

import json
import random
import time

import httpx
from loguru import logger

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

# Anthropic returns 429 under rate limiting and 500/502/503/529 for transient
# server-side issues; all are safe to retry.  Matches the list used by gemini.py
# so both upstream LLM clients behave the same way under load.
_RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 529}

_DEFAULT_TIMEOUT = 60
_DEFAULT_MAX_RETRIES = 3


def _post_with_retry(
    url: str,
    payload: dict,
    headers: dict,
    *,
    timeout: int,
    max_retries: int,
    label: str,
) -> httpx.Response:
    """POST JSON with exponential backoff on transient failures.

    Retries ``max_retries`` times on network timeouts and on
    ``_RETRIABLE_STATUS_CODES``.  Non-retriable statuses raise immediately.
    """
    last_exc: Exception | None = None
    for attempt in range(1 + max_retries):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = 2**attempt + random.uniform(0, 0.5)
                logger.warning(
                    "{} timeout, retrying in {:.1f}s (attempt {}/{})",
                    label,
                    delay,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(delay)
            continue

        if resp.status_code < 400:
            return resp

        if resp.status_code not in _RETRIABLE_STATUS_CODES:
            resp.raise_for_status()

        last_exc = httpx.HTTPStatusError(
            message=f"HTTP {resp.status_code}",
            request=resp.request,
            response=resp,
        )
        if attempt < max_retries:
            delay = 2**attempt + random.uniform(0, 0.5)  # ~1s, ~2s, ~4s
            logger.warning(
                "{} returned {}, retrying in {:.1f}s (attempt {}/{})",
                label,
                resp.status_code,
                delay,
                attempt + 1,
                max_retries,
            )
            time.sleep(delay)

    assert last_exc is not None
    raise last_exc


def judge_eval_output(
    api_key: str,
    model: str,
    eval_case_name: str,
    eval_criteria: str,
    agent_output: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    max_retries: int = _DEFAULT_MAX_RETRIES,
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
    response = _post_with_retry(
        _ANTHROPIC_API_URL,
        payload,
        headers,
        timeout=timeout,
        max_retries=max_retries,
        label=f"Anthropic judge ({model})",
    )

    data = response.json()
    raw_text = data["content"][0]["text"]

    result = _parse_judge_response(raw_text)
    logger.debug("Judge verdict for '{}': {}", eval_case_name, result["verdict"])
    return result


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
