"""Tests for stale token detection in get_current_user."""

from datetime import UTC, datetime, timedelta

from jose import jwt


class TestStaleTokenDetection:
    def test_token_without_github_orgs_returns_401(self, test_settings, client):
        """A JWT missing the github_orgs claim should be rejected as stale."""
        # Manually craft a token without the github_orgs claim
        now = datetime.now(UTC)
        payload = {
            "sub": "12345678-1234-5678-1234-567812345678",
            "username": "olduser",
            "exp": now + timedelta(hours=1),
            "iat": now,
        }
        stale_token = jwt.encode(
            payload,
            test_settings.jwt_secret,
            algorithm=test_settings.jwt_algorithm,
        )

        resp = client.get(
            "/v1/orgs",
            headers={"Authorization": f"Bearer {stale_token}"},
        )

        assert resp.status_code == 401
        assert "outdated" in resp.json()["detail"]
        assert "dhub login" in resp.json()["detail"]

    def test_token_with_github_orgs_passes(self, test_settings, client):
        """A JWT containing the github_orgs claim should pass auth."""
        now = datetime.now(UTC)
        payload = {
            "sub": "12345678-1234-5678-1234-567812345678",
            "username": "newuser",
            "github_orgs": ["my-org"],
            "exp": now + timedelta(hours=1),
            "iat": now,
        }
        token = jwt.encode(
            payload,
            test_settings.jwt_secret,
            algorithm=test_settings.jwt_algorithm,
        )

        resp = client.get(
            "/v1/orgs",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Should not be 401 — the request passes auth
        assert resp.status_code != 401

    def test_token_with_empty_github_orgs_passes(self, test_settings, client):
        """A JWT with an empty github_orgs list is valid (claim is present)."""
        now = datetime.now(UTC)
        payload = {
            "sub": "12345678-1234-5678-1234-567812345678",
            "username": "solouser",
            "github_orgs": [],
            "exp": now + timedelta(hours=1),
            "iat": now,
        }
        token = jwt.encode(
            payload,
            test_settings.jwt_secret,
            algorithm=test_settings.jwt_algorithm,
        )

        resp = client.get(
            "/v1/orgs",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert resp.status_code != 401


class TestMalformedTokenPayload:
    """Signed-but-malformed JWTs must return 401, never 500.

    Before the deps refactor, ``UUID(payload["sub"])`` and
    ``payload["username"]`` would raise ``KeyError`` / ``ValueError`` and
    escape the handler — leaking a 500 status code (and a stack trace in
    debug builds) for attacker-controlled input.
    """

    def _encode(self, test_settings, payload: dict) -> str:
        return jwt.encode(payload, test_settings.jwt_secret, algorithm=test_settings.jwt_algorithm)

    def test_token_missing_sub_returns_401(self, test_settings, client):
        now = datetime.now(UTC)
        token = self._encode(
            test_settings,
            {
                "username": "alice",
                "github_orgs": ["my-org"],
                "exp": now + timedelta(hours=1),
                "iat": now,
            },
        )
        resp = client.get("/v1/orgs", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_token_missing_username_returns_401(self, test_settings, client):
        now = datetime.now(UTC)
        token = self._encode(
            test_settings,
            {
                "sub": "12345678-1234-5678-1234-567812345678",
                "github_orgs": ["my-org"],
                "exp": now + timedelta(hours=1),
                "iat": now,
            },
        )
        resp = client.get("/v1/orgs", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_token_with_invalid_sub_uuid_returns_401(self, test_settings, client):
        now = datetime.now(UTC)
        token = self._encode(
            test_settings,
            {
                "sub": "not-a-uuid",
                "username": "alice",
                "github_orgs": ["my-org"],
                "exp": now + timedelta(hours=1),
                "iat": now,
            },
        )
        resp = client.get("/v1/orgs", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
