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

# Retriable server / rate-limit statuses. A single flaky 429/502 on a
# gauntlet case used to fail the whole judgement.
_RETRIABLE_STATUS_CODES = {429, 500, 502, 503, 529}
_JUDGE_MAX_RETRIES = 3
_JUDGE_TIMEOUT_SECONDS = 60

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
    response = _post_with_retry(payload, headers, eval_case_name)
    response.raise_for_status()

    data = response.json()
    raw_text = data["content"][0]["text"]

    result = _parse_judge_response(raw_text)
    logger.debug("Judge verdict for '{}': {}", eval_case_name, result["verdict"])
    return result


def _post_with_retry(payload: dict, headers: dict, eval_case_name: str) -> httpx.Response:
    """POST to the Anthropic API with exponential backoff on transient errors.

    Mirrors the behaviour of ``gemini_request_with_retry``: retry on 429/5xx
    and on ``httpx.TimeoutException`` up to ``_JUDGE_MAX_RETRIES`` times with
    jittered exponential backoff. Non-retriable errors (4xx auth/validation)
    return the response immediately so the caller can raise_for_status.
    """
    last_exc: Exception | None = None
    for attempt in range(1 + _JUDGE_MAX_RETRIES):
        try:
            resp = httpx.post(
                _ANTHROPIC_API_URL,
                json=payload,
                headers=headers,
                timeout=_JUDGE_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException as exc:
            last_exc = exc
            if attempt >= _JUDGE_MAX_RETRIES:
                raise
            delay = 2**attempt + random.uniform(0, 0.5)
            logger.warning(
                "Anthropic judge timeout for '{}', retrying in {:.1f}s (attempt {}/{})",
                eval_case_name,
                delay,
                attempt + 1,
                _JUDGE_MAX_RETRIES,
            )
            time.sleep(delay)
            continue

        if resp.status_code < 400 or resp.status_code not in _RETRIABLE_STATUS_CODES:
            return resp

        if attempt >= _JUDGE_MAX_RETRIES:
            return resp
        delay = 2**attempt + random.uniform(0, 0.5)
        logger.warning(
            "Anthropic judge returned {} for '{}', retrying in {:.1f}s (attempt {}/{})",
            resp.status_code,
            eval_case_name,
            delay,
            attempt + 1,
            _JUDGE_MAX_RETRIES,
        )
        time.sleep(delay)

    # The loop always returns or raises before reaching here; this line
    # exists to satisfy the type checker on unreachable paths.
    raise last_exc if last_exc else RuntimeError("Anthropic judge retry loop exited unexpectedly")


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
