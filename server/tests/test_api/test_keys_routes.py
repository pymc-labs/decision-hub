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

    def test_store_key_rejects_oversized_value(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        """A > 8KiB value must be rejected at validation, not encrypted+persisted.

        Historical hole: `value: str` had no `max_length`, so an authenticated
        caller could POST a multi-MB value; the endpoint fully buffered it,
        Fernet-encrypted it (~12x memory overhead), and wrote it to Postgres.
        """
        # 8193 chars — one over the cap. Payload is small enough to send from
        # the test but large enough to trigger the field-level validator.
        oversized = "x" * 8193
        resp = client.post(
            "/v1/keys",
            json={"key_name": "openai", "value": oversized},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_store_key_rejects_oversized_name(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        """Key name is bounded to 64 chars and must match ^[A-Za-z0-9_-]+$."""
        resp = client.post(
            "/v1/keys",
            json={"key_name": "x" * 65, "value": "sk-12345"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_store_key_rejects_invalid_name_chars(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        """Key names with whitespace / slashes / dots are rejected."""
        for bad in ["with space", "with/slash", "with.dot", ""]:
            resp = client.post(
                "/v1/keys",
                json={"key_name": bad, "value": "sk-12345"},
                headers=auth_headers,
            )
            assert resp.status_code == 422, f"expected 422 for name={bad!r}"


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
