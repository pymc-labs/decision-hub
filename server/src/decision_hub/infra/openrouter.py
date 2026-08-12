"""OpenRouter LLM transport (OpenAI-compatible chat completions API).

Default backend for the gauntlet LLM judge and skill classification,
using Qwen via OpenRouter. The judge prompts and response parsing live
in ``infra.gemini`` — this module only provides the transport, so both
backends run identical prompts and the provider can be swapped via
settings without behavioral drift.
"""

import random
import time

import httpx
from loguru import logger

OPENROUTER_API_URL = "https://openrouter.ai/api/v1"

_RETRIABLE_STATUS_CODES = {403, 429, 500, 502, 503}


def create_openrouter_client(api_key: str, *, http_client: httpx.Client | None = None) -> dict:
    """Create an OpenRouter client configuration.

    Mirrors ``create_gemini_client``: a plain dict keeps the interface
    simple and lets the judge functions in ``infra.gemini`` dispatch on
    the ``provider`` field. When ``http_client`` is provided it is
    reused for all API calls, avoiding repeated TCP+TLS handshakes
    during a gauntlet run.
    """
    return {
        "provider": "openrouter",
        "api_key": api_key,
        "base_url": OPENROUTER_API_URL,
        "http_client": http_client,
    }


def openrouter_request_with_retry(
    client: dict,
    url: str,
    payload: dict,
    *,
    timeout: int = 60,
    max_retries: int = 3,
    label: str = "OpenRouter API",
) -> dict:
    """POST to an OpenRouter endpoint with retry and exponential backoff.

    Retries on transient HTTP errors (403, 429, 500, 502, 503) and
    timeouts. Non-retriable errors propagate immediately.
    """
    headers = {"Authorization": f"Bearer {client['api_key']}"}
    shared = client.get("http_client")

    last_exc: Exception | None = None
    for attempt in range(1 + max_retries):
        try:
            if shared is not None:
                resp = shared.post(url, headers=headers, json=payload, timeout=timeout)
            else:
                with httpx.Client(timeout=timeout) as http_client:
                    resp = http_client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = 2**attempt + random.uniform(0, 0.5)
                logger.warning(
                    "{} timeout for {}, retrying in {:.1f}s (attempt {}/{})",
                    label,
                    url,
                    delay,
                    attempt + 1,
                    max_retries,
                )
                time.sleep(delay)
            continue

        if resp.status_code < 400:
            return resp.json()

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
                "{} returned {} for {}, retrying in {:.1f}s (attempt {}/{})",
                label,
                resp.status_code,
                url,
                delay,
                attempt + 1,
                max_retries,
            )
            time.sleep(delay)

    raise last_exc  # type: ignore[misc]


def _extract_content(data: dict) -> str:
    """Safely extract the assistant message text from a chat completion.

    Handles empty ``choices`` or missing ``message``/``content`` fields
    (e.g. provider errors, content filters) by returning "".
    """
    choices = data.get("choices", [])
    if not choices:
        return ""
    content = choices[0].get("message", {}).get("content")
    return content or ""


def openrouter_generate(
    client: dict,
    model: str,
    prompt: str,
    *,
    temperature: float = 0.0,
    timeout: int = 60,
    max_retries: int = 3,
) -> str:
    """Run a single-turn chat completion and return the response text.

    Reasoning is explicitly disabled: the gauntlet judges expect a bare
    JSON response, and reasoning tokens add latency and cost without
    changing the verdict format.
    """
    url = f"{client['base_url']}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "reasoning": {"enabled": False},
    }
    data = openrouter_request_with_retry(client, url, payload, timeout=timeout, max_retries=max_retries)
    return _extract_content(data)
