"""Tests for decision_hub.api.keys_routes -- API key management endpoints."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID

from fastapi.testclient import TestClient

from decision_hub.models import UserApiKey


class TestStoreKey:
    """POST /v1/keys -- encrypt and store an API key."""

    @patch("decision_hub.api.keys_routes.insert_api_key")
    def test_store_key_success(
        self,
        mock_insert: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Storing a key should return the key name and creation timestamp."""
        now = datetime.now(UTC)
        mock_insert.return_value = UserApiKey(
            id=UUID("cccccccc-0000-0000-0000-000000000001"),
            user_id=sample_user_id,
            key_name="openai",
            encrypted_value=b"encrypted-bytes",
            created_at=now,
        )

        resp = client.post(
            "/v1/keys",
            json={"key_name": "openai", "value": "sk-12345"},
            headers=auth_headers,
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["key_name"] == "openai"
        assert "created_at" in data

    def test_store_key_unauthenticated(self, client: TestClient) -> None:
        """Missing auth should return 401."""
        resp = client.post(
            "/v1/keys",
            json={"key_name": "openai", "value": "sk-12345"},
        )
        assert resp.status_code == 401


class TestListKeys:
    """GET /v1/keys -- list stored API key names."""

    @patch("decision_hub.api.keys_routes.list_api_keys")
    def test_list_keys(
        self,
        mock_list: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
        sample_user_id: UUID,
    ) -> None:
        """Should return a list of key summaries (no values)."""
        now = datetime.now(UTC)
        mock_list.return_value = [
            UserApiKey(
                id=UUID("cccccccc-0000-0000-0000-000000000001"),
                user_id=sample_user_id,
                key_name="openai",
                encrypted_value=b"encrypted",
                created_at=now,
            ),
            UserApiKey(
                id=UUID("cccccccc-0000-0000-0000-000000000002"),
                user_id=sample_user_id,
                key_name="anthropic",
                encrypted_value=b"encrypted",
                created_at=now,
            ),
        ]

        resp = client.get("/v1/keys", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        key_names = {item["key_name"] for item in data}
        assert key_names == {"openai", "anthropic"}


class TestDeleteKey:
    """DELETE /v1/keys/{key_name} -- delete a stored key."""

    @patch("decision_hub.api.keys_routes.delete_api_key")
    def test_delete_key_success(
        self,
        mock_delete: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 204 when a key is successfully deleted."""
        mock_delete.return_value = True

        resp = client.delete("/v1/keys/openai", headers=auth_headers)

        assert resp.status_code == 204

    @patch("decision_hub.api.keys_routes.delete_api_key")
    def test_delete_key_not_found(
        self,
        mock_delete: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Should return 404 when the key does not exist."""
        mock_delete.return_value = False

        resp = client.delete("/v1/keys/nonexistent", headers=auth_headers)

        assert resp.status_code == 404
