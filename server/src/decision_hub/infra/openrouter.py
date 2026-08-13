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

# Routing policy sent with every completion request.
#
# OpenRouter's default is price-weighted load balancing across whichever
# upstream providers host the model, so without this the same skill can be
# judged by a different host — at a different quantization — on each
# publish, making a gauntlet verdict (and the public A-F grade) irreproducible.
#
#   data_collection: skill source code, including private skills, is sent
#     in the prompt. "deny" excludes providers that may store or train on it.
#   require_parameters: only route to providers that honour every parameter
#     we send (temperature, max_tokens, reasoning) instead of dropping them.
#
# Deliberately NOT filtering on `quantizations`: providers that declare no
# quantization are excluded by that filter, and for qwen/qwen3.7-flash that
# is every one of them (verified live — the request 404s with "No endpoints
# found for the request with quantization"). Pin OPENROUTER_PROVIDERS instead
# if a specific host is required.
_PROVIDER_POLICY = {
    "data_collection": "deny",
    "require_parameters": True,
}

# Cap on response length. Judge prompts ask for one JSON object per
# finding, so the ceiling has to clear the largest realistic batch; a
# truncated array is unparseable and fails every finding closed.
DEFAULT_MAX_TOKENS = 16384


def create_openrouter_client(
    api_key: str,
    *,
    http_client: httpx.Client | None = None,
    providers: list[str] | None = None,
) -> dict:
    """Create an OpenRouter client configuration.

    Mirrors ``create_gemini_client``: a plain dict keeps the interface
    simple and lets the judge functions in ``infra.gemini`` dispatch on
    the ``provider`` field. When ``http_client`` is provided it is
    reused for all API calls, avoiding repeated TCP+TLS handshakes
    during a gauntlet run.

    ``providers`` pins routing to specific upstream provider slugs, in
    order, and disables OpenRouter's fallback to unlisted hosts.
    """
    return {
        "provider": "openrouter",
        "api_key": api_key,
        "base_url": OPENROUTER_API_URL,
        "http_client": http_client,
        "providers": providers or [],
    }


def _build_provider_routing(client: dict) -> dict:
    """Build the ``provider`` routing block for a completion request."""
    routing = dict(_PROVIDER_POLICY)
    pinned = client.get("providers")
    if pinned:
        routing["order"] = list(pinned)
        routing["allow_fallbacks"] = False
    return routing


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


def _log_if_truncated(data: dict, model: str) -> None:
    """Warn when the response was cut off by the token cap.

    A truncated response is unparseable JSON, which the judges treat the
    same as a garbage response: every finding fails closed to dangerous
    and the skill gets a spurious grade F. Without this log the two
    causes are indistinguishable after the fact.
    """
    choices = data.get("choices", [])
    if not choices or choices[0].get("finish_reason") != "length":
        return
    usage = data.get("usage") or {}
    logger.warning(
        "OpenRouter response truncated (finish_reason=length) model={} provider={} completion_tokens={} — "
        "the judge response is incomplete and will fail closed; raise max_tokens",
        model,
        data.get("provider", "unknown"),
        usage.get("completion_tokens", "unknown"),
    )


def openrouter_generate(
    client: dict,
    model: str,
    prompt: str,
    *,
    temperature: float = 0.0,
    timeout: int = 60,
    max_retries: int = 3,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """Run a single-turn chat completion and return the response text.

    Reasoning is explicitly disabled: the gauntlet judges expect a bare
    JSON response, and reasoning tokens add latency and cost without
    changing the verdict format.

    ``max_tokens`` is always sent explicitly rather than left to the
    provider default, which varies by upstream host.
    """
    url = f"{client['base_url']}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "reasoning": {"enabled": False},
        "provider": _build_provider_routing(client),
    }
    data = openrouter_request_with_retry(client, url, payload, timeout=timeout, max_retries=max_retries)
    _log_if_truncated(data, model)
    return _extract_content(data)
