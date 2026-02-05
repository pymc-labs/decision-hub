"""GitHub Device Flow OAuth implementation.

Implements the GitHub OAuth Device Flow for CLI-based authentication:
1. Request a device code from GitHub.
2. User visits the verification URL and enters the user code.
3. Poll GitHub until the user authorizes or the flow expires.
4. Fetch the authenticated user's profile with the access token.

All HTTP requests use httpx with synchronous calls and explicit Accept headers
for GitHub's JSON API responses.
"""

import time

import httpx

from decision_hub.models import DeviceCodeResponse

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

_ACCEPT_JSON = "application/json"


def request_device_code(client_id: str) -> DeviceCodeResponse:
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
    response = httpx.post(
        GITHUB_DEVICE_CODE_URL,
        data={"client_id": client_id},
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


def poll_for_access_token(
    client_id: str, device_code: str, interval: int = 5
) -> str:
    """Poll GitHub for an access token after the user authorizes the device.

    Continuously polls the GitHub token endpoint at the specified interval
    until the user completes authorization, the code expires, or access is
    explicitly denied.

    Args:
        client_id: The GitHub OAuth App client ID.
        device_code: The device code from request_device_code().
        interval: Seconds between polling attempts (default: 5).

    Returns:
        The OAuth access token string.

    Raises:
        RuntimeError: If the user denies access or the device code expires.
        httpx.HTTPStatusError: If the GitHub API returns an unexpected error.
    """
    while True:
        time.sleep(interval)
        response = httpx.post(
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
        if error == "authorization_pending":
            # User hasn't authorized yet; keep polling
            continue
        if error == "slow_down":
            # GitHub asked us to back off; increase interval by 5 seconds
            interval += 5
            continue
        if error == "expired_token":
            raise RuntimeError(
                "Device code expired. Please restart the login flow."
            )
        if error == "access_denied":
            raise RuntimeError("User denied the authorization request.")

        # Unexpected error from GitHub
        raise RuntimeError(
            f"Unexpected error during device flow polling: {error} - "
            f"{data.get('error_description', 'no description')}"
        )


def get_github_user(access_token: str) -> dict:
    """Fetch the authenticated user's GitHub profile.

    Args:
        access_token: A valid GitHub OAuth access token.

    Returns:
        A dictionary with at least 'id' (int) and 'login' (str) keys
        from the GitHub user profile.

    Raises:
        httpx.HTTPStatusError: If the GitHub API returns an error response.
    """
    response = httpx.get(
        GITHUB_USER_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": _ACCEPT_JSON,
        },
    )
    response.raise_for_status()
    return response.json()
