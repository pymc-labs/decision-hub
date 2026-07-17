"""Unit tests for ``update_org_github_metadata``.

Focus: the function must not clobber existing DB columns with ``None``
when GitHub returns a null for an optional field (blog, email,
description, avatar_url). Passing ``None`` should omit the column from
the UPDATE, not set it to NULL.
"""

from unittest.mock import MagicMock
from uuid import uuid4

from decision_hub.infra.database import update_org_github_metadata


class TestUpdateOrgGithubMetadata:
    """The generated UPDATE must skip columns whose input is None."""

    def _executed_stmt(self, conn: MagicMock):
        assert conn.execute.call_count == 1, "expected exactly one UPDATE"
        return conn.execute.call_args.args[0]

    def _values_from_stmt(self, stmt) -> dict[str, object]:
        """Extract the {column: bind_value} mapping from the SQLAlchemy Update."""
        params = stmt.compile().params
        # Bind param names are prefixed by the column name; keys map cleanly.
        return params

    def test_none_fields_are_omitted_from_update(self) -> None:
        """When GitHub returns null for a field, do not overwrite the DB row.

        Regression: the previous implementation passed each keyword
        straight into ``.values(...)``, so a payload like
        ``{blog: None}`` translated to ``SET blog = NULL`` — silently
        wiping a value the user had set at some point in the past.
        """
        conn = MagicMock()
        org_id = uuid4()

        update_org_github_metadata(
            conn,
            org_id,
            avatar_url="https://avatars.example.com/x.png",
            email=None,
            description=None,
            blog=None,
        )

        stmt = self._executed_stmt(conn)
        params = self._values_from_stmt(stmt)

        # avatar_url made it through; the None fields did not.
        assert "avatar_url" in params
        assert params["avatar_url"] == "https://avatars.example.com/x.png"
        assert "email" not in params
        assert "description" not in params
        assert "blog" not in params

    def test_all_none_still_bumps_synced_at(self) -> None:
        """Even when every field is None the sync timestamp must be bumped.

        Otherwise the 24-hour dedup cache in ``sync_org_github_metadata``
        would keep re-attempting the API call every login.
        """
        conn = MagicMock()
        org_id = uuid4()
        update_org_github_metadata(conn, org_id)

        stmt = self._executed_stmt(conn)
        # The compiled statement must set exactly `github_synced_at` and
        # nothing else — no columns were provided.
        columns = [str(c) for c in stmt.compile().statement._values]
        assert any("github_synced_at" in c for c in columns), columns
        # None of the input columns should be present.
        for col in ("avatar_url", "email", "description", "blog"):
            assert not any(col in c for c in columns), f"{col} leaked into UPDATE with all-None input"

    def test_empty_string_writes_empty_string(self) -> None:
        """Callers that genuinely want to clear a field pass an empty string.

        This is the documented escape hatch — the fix distinguishes
        "not provided" (None → skip) from "clear this value" ("").
        """
        conn = MagicMock()
        org_id = uuid4()
        update_org_github_metadata(conn, org_id, blog="")

        params = self._values_from_stmt(self._executed_stmt(conn))
        assert "blog" in params
        assert params["blog"] == ""
