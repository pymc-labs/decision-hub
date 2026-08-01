"""Database function tests for organization metadata helpers.

Uses mocked connections; the emitted SQLAlchemy statement is compiled
and inspected so a regression to the old "always overwrite" behaviour
is caught.
"""

from unittest.mock import MagicMock
from uuid import uuid4

from decision_hub.infra.database import update_org_github_metadata


class TestUpdateOrgGithubMetadata:
    def _compiled_values(self, conn: MagicMock) -> str:
        """Return the compiled SQL of the last UPDATE with literal binds."""
        conn.execute.assert_called_once()
        stmt = conn.execute.call_args[0][0]
        return str(stmt.compile(compile_kwargs={"literal_binds": True}))

    def test_omits_none_fields_from_update(self):
        """Regression: when GitHub returns null for ``description`` /
        ``blog`` / ``email`` (very common for org accounts), the sync
        used to overwrite the stored value with NULL — silently wiping
        data that was populated on a prior sync or set manually. The
        helper must only update fields the caller explicitly provided.
        """
        conn = MagicMock()
        org_id = uuid4()

        update_org_github_metadata(
            conn,
            org_id,
            avatar_url="https://gh/avatar.png",
            email=None,
            description=None,
            blog=None,
        )

        compiled = self._compiled_values(conn)
        assert "avatar_url" in compiled
        assert "github_synced_at" in compiled
        # These must NOT appear in the SET clause — they were None.
        assert "description=" not in compiled.replace(" ", "")
        assert "blog=" not in compiled.replace(" ", "")
        assert "email=" not in compiled.replace(" ", "")

    def test_updates_all_provided_fields(self):
        conn = MagicMock()
        org_id = uuid4()

        update_org_github_metadata(
            conn,
            org_id,
            avatar_url="https://gh/avatar.png",
            email="alice@example.com",
            description="hello",
            blog="https://alice.dev",
        )

        compiled = self._compiled_values(conn)
        assert "avatar_url" in compiled
        assert "email" in compiled
        assert "description" in compiled
        assert "blog" in compiled
        assert "github_synced_at" in compiled

    def test_empty_string_is_explicit_clear(self):
        """An empty string is a caller-provided value (``""``, not None)
        and should reach the DB — this is how a user explicitly clears
        a field via the API."""
        conn = MagicMock()
        org_id = uuid4()

        update_org_github_metadata(conn, org_id, description="")

        compiled = self._compiled_values(conn)
        assert "description" in compiled

    def test_all_none_still_bumps_sync_timestamp(self):
        """Even when every metadata field is null, the helper must
        update ``github_synced_at`` so ``sync_org_github_metadata``'s
        24 h TTL check moves forward and does not re-hit GitHub every
        request."""
        conn = MagicMock()
        org_id = uuid4()

        update_org_github_metadata(conn, org_id)

        compiled = self._compiled_values(conn)
        assert "github_synced_at" in compiled
