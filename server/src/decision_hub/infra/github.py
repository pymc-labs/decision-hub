"""GitHub Device Flow OAuth implementation.

Implements the GitHub OAuth Device Flow for CLI-based authentication:
1. Request a device code from GitHub.
2. User visits the verification URL and enters the user code.
3. Poll GitHub until the user authorizes or the flow expires.
4. Fetch the authenticated user's profile with the access token.

All HTTP requests use httpx.AsyncClient for non-blocking I/O within
the FastAPI async event loop.
"""

import httpx

from decision_hub.models import DeviceCodeResponse

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_USER_ORGS_URL = "https://api.github.com/user/orgs"

_ACCEPT_JSON = "application/json"


class AuthorizationPending(Exception):
    """Raised when the user has not yet completed GitHub authorization."""


async def request_device_code(client_id: str) -> DeviceCodeResponse:
    """Request a device code from GitHub for the OAuth Device Flow.

    Initiates the device authorization flow by requesting a device code and
    user code pair. The user must visit the verification URL and enter the
    user code to authorize the application.

    Args:
        client_id: The GitHub OAuth App client ID.

    Returns:
        A DeviceCodeResponse containing the device_code, user_code,
        verification_uri, and polling interval.

    Raises:
        httpx.HTTPStatusError: If the GitHub API returns an error response.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GITHUB_DEVICE_CODE_URL,
            data={"client_id": client_id, "scope": "read:org"},
            headers={"Accept": _ACCEPT_JSON},
        )
    response.raise_for_status()
    data = response.json()
    return DeviceCodeResponse(
        device_code=data["device_code"],
        user_code=data["user_code"],
        verification_uri=data["verification_uri"],
        interval=data.get("interval", 5),
    )


async def poll_for_access_token(
    client_id: str, device_code: str, interval: int = 5
) -> str:
    """Check GitHub once for an access token.

    Makes a single request to the GitHub token endpoint. The client is
    responsible for retrying when AuthorizationPending is raised.

    Args:
        client_id: The GitHub OAuth App client ID.
        device_code: The device code from request_device_code().
        interval: Ignored (kept for signature compatibility).

    Returns:
        The OAuth access token string.

    Raises:
        AuthorizationPending: If the user hasn't authorized yet.
        RuntimeError: If the user denies access or the device code expires.
        httpx.HTTPStatusError: If the GitHub API returns an unexpected error.
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            GITHUB_ACCESS_TOKEN_URL,
            data={
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"Accept": _ACCEPT_JSON},
        )
    response.raise_for_status()
    data = response.json()

    if "access_token" in data:
        return data["access_token"]

    error = data.get("error")
    if error in ("authorization_pending", "slow_down"):
        raise AuthorizationPending()
    if error == "expired_token":
        raise RuntimeError(
            "Device code expired. Please restart the login flow."
        )
    if error == "access_denied":
        raise RuntimeError("User denied the authorization request.")

    raise RuntimeError(
        f"Unexpected error during device flow polling: {error} - "
        f"{data.get('error_description', 'no description')}"
    )


async def get_github_user(access_token: str) -> dict:
    """Fetch the authenticated user's GitHub profile.

    Args:
        access_token: A valid GitHub OAuth access token.

    Returns:
        A dictionary with at least 'id' (int) and 'login' (str) keys
        from the GitHub user profile.

    Raises:
        httpx.HTTPStatusError: If the GitHub API returns an error response.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": _ACCEPT_JSON,
            },
        )
    response.raise_for_status()
    return response.json()


def _parse_next_link(link_header: str) -> str | None:
    """Extract the 'next' URL from a GitHub Link header.

    GitHub uses RFC 5988 Link headers for pagination, e.g.:
        <https://api.github.com/user/orgs?page=2>; rel="next", ...

    Returns the URL for rel="next", or None if there is no next page.
    """
    for part in link_header.split(","):
        if 'rel="next"' in part:
            url = part.split(";")[0].strip().strip("<>")
            return url
    return None


async def list_user_orgs(access_token: str) -> list[dict]:
    """Fetch all organizations the authenticated user belongs to.

    Paginates through all results using the GitHub Link header.
    Each returned dict has at least a 'login' key with the org name.

    Args:
        access_token: A valid GitHub OAuth access token.

    Returns:
        A list of org dicts from the GitHub API.

    Raises:
        httpx.HTTPStatusError: If the GitHub API returns an error response.
    """
    orgs: list[dict] = []
    url: str | None = f"{GITHUB_USER_ORGS_URL}?per_page=100"

    async with httpx.AsyncClient() as client:
        while url is not None:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": _ACCEPT_JSON,
                },
            )
            response.raise_for_status()
            orgs.extend(response.json())

            link = response.headers.get("Link", "")
            url = _parse_next_link(link) if link else None

    return orgs


async def check_org_membership(access_token: str, org: str, username: str) -> bool:
    """Check whether a GitHub user is a member of an organization.

    Uses the public org members endpoint which works without the read:org
    scope. Falls back to checking public membership if the authenticated
    endpoint returns 403.

    Args:
        access_token: A valid GitHub OAuth access token.
        org: GitHub organization login (e.g. "pymc-labs").
        username: GitHub username to check.

    Returns:
        True if the user is a member of the organization.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.github.com/orgs/{org}/members/{username}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": _ACCEPT_JSON,
            },
        )
    if response.status_code == 204:
        return True
    if response.status_code == 404:
        return False

    # 302 means requester is not an org member — can't see membership list
    if response.status_code == 302:
        return False

    return False
