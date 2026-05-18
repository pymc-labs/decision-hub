"""Mint short-lived GitHub App installation tokens.

GitHub Apps authenticate via a two-step flow:
1. Sign a JWT with the App's private key (valid 10 min).
2. Exchange the JWT for an installation access token (valid ~1 hr).

The resulting token works everywhere a PAT does (REST, GraphQL, git clone)
and gets its own 12,500 req/hr rate-limit bucket.

GitHub installation tokens are valid for ~60 minutes, so we cache them
process-wide for slightly less than the official lifetime. The tracker
service and Modal entrypoints call ``mint_installation_token`` on every
poll/request; without caching that turns into one HTTP round-trip per
invocation and burns through the App's token-minting quota.
"""

import time

import httpx
import jwt

from decision_hub.infra.cache import TTLCache

# GitHub installation tokens nominally live ~60 minutes. Cache for slightly
# less so callers never receive a token that expires mid-use, while still
# avoiding the per-call mint when many requests fire in quick succession.
_TOKEN_TTL_SECONDS = 50 * 60
_token_cache: TTLCache = TTLCache(default_ttl=_TOKEN_TTL_SECONDS, max_size=16)


def _cache_key(app_id: str, installation_id: str) -> str:
    return f"{app_id}:{installation_id}"


def mint_installation_token(
    app_id: str,
    private_key: str,
    installation_id: str,
    *,
    use_cache: bool = True,
) -> str:
    """Mint (or return a cached) GitHub App installation token.

    A successful mint is cached per ``(app_id, installation_id)`` for
    :data:`_TOKEN_TTL_SECONDS` so concurrent callers in the same process
    reuse the same token. Tests and callers that need a guaranteed fresh
    mint can pass ``use_cache=False``.

    Raises ``httpx.HTTPStatusError`` on API failure.
    """
    key = _cache_key(app_id, installation_id)
    if use_cache:
        cached = _token_cache.get(key)
        if cached is not None:
            return cached

    now = int(time.time())
    payload = {
        "iat": now - 60,  # issued-at: 60s in the past to account for clock drift
        "exp": now + (10 * 60),  # expires in 10 minutes (GitHub max)
        "iss": app_id,
    }
    encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")

    response = httpx.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {encoded_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30,
    )
    response.raise_for_status()
    token: str = response.json()["token"]

    if use_cache:
        _token_cache.set(key, token)
    return token


def clear_token_cache() -> None:
    """Drop all cached installation tokens. Primarily for tests."""
    _token_cache.clear()
