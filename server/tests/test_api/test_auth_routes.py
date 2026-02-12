"""Tests for decision_hub.api.auth_routes -- GitHub Device Flow endpoints."""

from unittest.mock import MagicMock, patch
from uuid import UUID

import httpx
import respx
from fastapi.testclient import TestClient

from decision_hub.models import User


class TestStartDeviceFlow:
    """POST /auth/github/code -- initiates the GitHub Device Flow."""

    @respx.mock
    def test_returns_device_code_info(
        self,
        client: TestClient,
    ) -> None:
        """Should return user_code, verification_uri, device_code, interval."""
        route = respx.post("https://github.com/login/device/code").mock(
            return_value=httpx.Response(
                200,
                json={
                    "device_code": "dev-code-abc",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://github.com/login/device",
                    "interval": 5,
                },
            )
        )

        resp = client.post("/auth/github/code")

        assert resp.status_code == 200
        data = resp.json()
        assert data["device_code"] == "dev-code-abc"
        assert data["user_code"] == "ABCD-1234"
        assert data["verification_uri"] == "https://github.com/login/device"
        assert data["interval"] == 5

        # Verify the real request was built correctly
        request = route.calls[0].request
        assert request.headers["accept"] == "application/json"
        assert b"client_id=test-client-id" in request.content


class TestExchangeToken:
    """POST /auth/github/token -- exchanges device_code for a JWT."""

    @respx.mock
    @patch("decision_hub.api.auth_routes.sync_org_github_metadata")
    @patch("decision_hub.api.auth_routes.sync_user_orgs", return_value=["alice"])
    @patch("decision_hub.api.auth_routes.upsert_user")
    def test_returns_jwt_on_success(
        self,
        mock_upsert: MagicMock,
        mock_sync: MagicMock,
        mock_meta_sync: MagicMock,
        client: TestClient,
    ) -> None:
        """Successful flow should return an access_token, username, and orgs."""
        token_route = respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "gh-access-token-xyz"})
        )
        user_route = respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(200, json={"id": 42, "login": "alice"})
        )
        respx.get("https://api.github.com/user/orgs?per_page=100").mock(
            return_value=httpx.Response(200, json=[{"login": "cool-org"}])
        )
        mock_upsert.return_value = User(
            id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            github_id="42",
            username="alice",
        )

        resp = client.post(
            "/auth/github/token",
            json={"device_code": "dev-code-abc"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["username"] == "alice"
        assert data["orgs"] == ["alice"]

        # Verify the real GitHub requests were built correctly
        token_request = token_route.calls[0].request
        assert b"device_code=dev-code-abc" in token_request.content
        assert b"grant_type=" in token_request.content

        user_request = user_route.calls[0].request
        assert user_request.headers["authorization"] == "Bearer gh-access-token-xyz"

        mock_upsert.assert_called_once()
        mock_sync.assert_called_once()
        mock_meta_sync.assert_called_once()

    @respx.mock
    @patch("decision_hub.api.auth_routes.upsert_user")
    def test_rejects_user_not_in_required_org(
        self,
        mock_upsert: MagicMock,
        client: TestClient,
        test_settings: MagicMock,
    ) -> None:
        """When require_github_org is set, users outside that org get 403."""
        test_settings.require_github_org = "pymc-labs"
        test_settings.required_github_orgs = ["pymc-labs"]
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "gh-access-token-xyz"})
        )
        respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(200, json={"id": 42, "login": "outsider"})
        )
        org_route = respx.get("https://api.github.com/orgs/pymc-labs/members/outsider").mock(
            return_value=httpx.Response(404)
        )

        resp = client.post(
            "/auth/github/token",
            json={"device_code": "dev-code-abc"},
        )

        assert resp.status_code == 403
        assert "pymc-labs" in resp.json()["detail"]
        mock_upsert.assert_not_called()

        # Verify org membership check was sent with the GitHub token
        assert org_route.calls[0].request.headers["authorization"] == "Bearer gh-access-token-xyz"

    @respx.mock
    @patch("decision_hub.api.auth_routes.sync_org_github_metadata")
    @patch("decision_hub.api.auth_routes.sync_user_orgs", return_value=["alice", "pymc-labs"])
    @patch("decision_hub.api.auth_routes.upsert_user")
    def test_allows_user_in_required_org(
        self,
        mock_upsert: MagicMock,
        mock_sync: MagicMock,
        mock_meta_sync: MagicMock,
        client: TestClient,
        test_settings: MagicMock,
    ) -> None:
        """When require_github_org is set, members of that org can log in."""
        test_settings.require_github_org = "pymc-labs"
        test_settings.required_github_orgs = ["pymc-labs"]
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "gh-access-token-xyz"})
        )
        respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(200, json={"id": 42, "login": "alice"})
        )
        respx.get("https://api.github.com/orgs/pymc-labs/members/alice").mock(return_value=httpx.Response(204))
        respx.get("https://api.github.com/user/orgs?per_page=100").mock(
            return_value=httpx.Response(200, json=[{"login": "pymc-labs"}])
        )
        mock_upsert.return_value = User(
            id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            github_id="42",
            username="alice",
        )

        resp = client.post(
            "/auth/github/token",
            json={"device_code": "dev-code-abc"},
        )

        assert resp.status_code == 200
        assert resp.json()["username"] == "alice"
        assert resp.json()["orgs"] == ["alice", "pymc-labs"]

    @respx.mock
    @patch("decision_hub.api.auth_routes.sync_org_github_metadata")
    @patch("decision_hub.api.auth_routes.sync_user_orgs", return_value=["alice"])
    @patch("decision_hub.api.auth_routes.upsert_user")
    def test_graceful_degradation_when_org_fetch_fails(
        self,
        mock_upsert: MagicMock,
        mock_sync: MagicMock,
        mock_meta_sync: MagicMock,
        client: TestClient,
    ) -> None:
        """When GitHub org fetch fails, should still succeed with personal namespace."""
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "gh-access-token-xyz"})
        )
        respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(200, json={"id": 42, "login": "alice"})
        )
        # Org fetch fails with 500
        respx.get("https://api.github.com/user/orgs?per_page=100").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        mock_upsert.return_value = User(
            id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            github_id="42",
            username="alice",
        )

        resp = client.post(
            "/auth/github/token",
            json={"device_code": "dev-code-abc"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "alice"
        # sync_user_orgs should still be called with empty org list
        mock_sync.assert_called_once()
        args = mock_sync.call_args[0]
        assert args[2] == []  # github_org_logins should be empty

    @respx.mock
    @patch("decision_hub.api.auth_routes.sync_org_github_metadata", side_effect=RuntimeError("boom"))
    @patch("decision_hub.api.auth_routes.sync_user_orgs", return_value=["alice"])
    @patch("decision_hub.api.auth_routes.upsert_user")
    def test_metadata_sync_failure_does_not_block_login(
        self,
        mock_upsert: MagicMock,
        mock_sync: MagicMock,
        mock_meta_sync: MagicMock,
        client: TestClient,
    ) -> None:
        """When metadata sync fails, login should still succeed."""
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "gh-access-token-xyz"})
        )
        respx.get("https://api.github.com/user").mock(
            return_value=httpx.Response(200, json={"id": 42, "login": "alice"})
        )
        respx.get("https://api.github.com/user/orgs?per_page=100").mock(return_value=httpx.Response(200, json=[]))
        mock_upsert.return_value = User(
            id=UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"),
            github_id="42",
            username="alice",
        )

        resp = client.post(
            "/auth/github/token",
            json={"device_code": "dev-code-abc"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "alice"
        assert data["orgs"] == ["alice"]
        mock_meta_sync.assert_called_once()

    @respx.mock
    def test_authorization_pending_returns_428(
        self,
        client: TestClient,
    ) -> None:
        """AuthorizationPending should return 428."""
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"error": "authorization_pending"})
        )

        resp = client.post(
            "/auth/github/token",
            json={"device_code": "pending-code"},
        )

        assert resp.status_code == 428
        assert resp.json()["detail"] == "authorization_pending"

    @respx.mock
    def test_runtime_error_returns_502(
        self,
        client: TestClient,
    ) -> None:
        """RuntimeError from GitHub polling should return 502."""
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"error": "expired_token"})
        )

        resp = client.post(
            "/auth/github/token",
            json={"device_code": "expired-code"},
        )

        assert resp.status_code == 502
        assert "Device code expired" in resp.json()["detail"]

    @respx.mock
    def test_http_status_error_returns_502(
        self,
        client: TestClient,
    ) -> None:
        """httpx.HTTPStatusError from GitHub should return 502."""
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(503, text="Service Unavailable")
        )

        resp = client.post(
            "/auth/github/token",
            json={"device_code": "dev-code-abc"},
        )

        assert resp.status_code == 502
        assert "GitHub API error" in resp.json()["detail"]

    @respx.mock
    def test_github_user_fetch_error_returns_502(
        self,
        client: TestClient,
    ) -> None:
        """HTTPStatusError from get_github_user should return 502."""
        respx.post("https://github.com/login/oauth/access_token").mock(
            return_value=httpx.Response(200, json={"access_token": "gh-access-token-xyz"})
        )
        respx.get("https://api.github.com/user").mock(return_value=httpx.Response(500, text="Internal Server Error"))

        resp = client.post(
            "/auth/github/token",
            json={"device_code": "dev-code-abc"},
        )

        assert resp.status_code == 502
        assert "GitHub API error" in resp.json()["detail"]
