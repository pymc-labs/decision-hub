"""Mint short-lived GitHub App installation tokens.

GitHub Apps authenticate via a two-step flow:
1. Sign a JWT with the App's private key (valid 10 min).
2. Exchange the JWT for an installation access token (valid ~1 hr).

The resulting token works everywhere a PAT does (REST, GraphQL, git clone)
and gets its own 12,500 req/hr rate-limit bucket.
"""

import time

import httpx
import jwt


def mint_installation_token(
    app_id: str,
    private_key: str,
    installation_id: str,
) -> str:
    """Mint a short-lived GitHub App installation token (valid ~1 hr).

    Raises ``httpx.HTTPStatusError`` on API failure.
    """
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
    return response.json()["token"]
