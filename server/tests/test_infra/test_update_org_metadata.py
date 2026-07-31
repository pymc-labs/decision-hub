"""Tests for ``update_org_github_metadata`` null-safety.

Regression sentinel for the bug: GitHub's ``/users`` and ``/orgs`` responses
often omit ``email``/``description``/``blog``.  Before the fix, the daily
login-driven metadata re-sync unconditionally overwrote those DB columns with
``None`` — silently nulling any backfilled value.

The tests inspect the compiled SQL to assert that:

- Fields whose caller-supplied value is ``None`` are NOT emitted at all
  (so the existing row value is preserved by the UPDATE).
- ``github_synced_at`` is always set to ``now()`` so the TTL check still
  advances even when nothing else was written.
- Fields with a genuine value are still written normally.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from decision_hub.infra.database import update_org_github_metadata


def _last_compiled_update(conn: MagicMock) -> sa.Update:
    """Return the last ``sa.Update`` statement that was executed on the mock."""
    stmt = conn.execute.call_args[0][0]
    assert isinstance(stmt, sa.Update), f"expected UPDATE, got {type(stmt).__name__}"
    return stmt


def _columns_set_by(stmt: sa.Update) -> set[str]:
    """Extract the set of column names that the UPDATE will actually write.

    Uses SQLAlchemy's compiled ``_values`` to introspect the statement — this
    is the same accessor SQLAlchemy uses internally when it produces the SET
    clause of the emitted SQL.
    """
    # `stmt._values` maps Column -> literal on modern SQLAlchemy 2.x, but
    # falling back to compiling and re-parsing makes the test resilient to
    # internal API drift.
    compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False})
    return set(compiled.params.keys())


class TestUpdateOrgGithubMetadataNullSafety:
    """The daily-sync clobber bug must never come back."""

    def test_none_valued_fields_are_omitted_from_update(self) -> None:
        """A None-valued kwarg must NOT appear in the SET clause.

        Failing scenario before the fix: GitHub returns
        ``{"avatar_url": ..., "email": null, "description": null, "blog": null}``
        for an org.  The caller does ``update_org_github_metadata(email=None, …)``.
        Under the old behaviour the DB row's ``email`` column was overwritten
        with NULL, erasing whatever was backfilled by
        ``scripts/backfill_org_metadata.py``.
        """
        conn = MagicMock()

        update_org_github_metadata(
            conn,
            uuid4(),
            avatar_url="https://avatar.example/x.png",
            email=None,
            description=None,
            blog=None,
        )

        cols = _columns_set_by(_last_compiled_update(conn))
        assert "avatar_url" in cols
        assert "email" not in cols
        assert "description" not in cols
        assert "blog" not in cols

    def test_all_fields_populated_writes_everything(self) -> None:
        """When every field is provided, all columns are written normally."""
        conn = MagicMock()

        update_org_github_metadata(
            conn,
            uuid4(),
            avatar_url="https://a",
            email="e@x.com",
            description="hi",
            blog="https://b",
        )

        cols = _columns_set_by(_last_compiled_update(conn))
        assert {"avatar_url", "email", "description", "blog"}.issubset(cols)

    def test_all_none_still_updates_synced_at(self) -> None:
        """A call with no metadata still bumps ``github_synced_at``.

        The TTL check in ``sync_org_github_metadata`` depends on this
        timestamp advancing; if it didn't, an org whose GitHub response was
        entirely empty would be re-fetched on every sync forever.
        """
        conn = MagicMock()

        update_org_github_metadata(
            conn,
            uuid4(),
            avatar_url=None,
            email=None,
            description=None,
            blog=None,
        )

        stmt = _last_compiled_update(conn)
        # ``github_synced_at`` is set to ``func.now()`` — check the raw
        # `_values` map instead of ``compile().params`` because SQL functions
        # don't produce a bind param.
        columns_set = {col.key if hasattr(col, "key") else str(col) for col in stmt._values}
        assert "github_synced_at" in columns_set
        # None of the caller-supplied fields make it into the UPDATE.
        assert columns_set == {"github_synced_at"}
