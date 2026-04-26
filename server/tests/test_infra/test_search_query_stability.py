"""Tests verifying that paginated/limited search queries are deterministic.

CLAUDE.md ("SQL query correctness"): every query with ``LIMIT`` must include
an explicit ``ORDER BY`` with a unique tiebreaker.  ``ts_rank_cd`` and pgvector
``cosine_distance`` can produce ties on short queries or normalised embeddings,
which used to flip results between requests.  These tests pin the tiebreakers
so a regression at the SQL level fails fast in CI rather than silently across
production deployments.

We compile the SQLAlchemy statement against the postgres dialect and assert on
the ``ORDER BY`` clause — same shape as the pattern in
``test_tracker_db.py::TestClaimDueTrackers``.  Postgres-aware compilation is
required because the FTS branch uses ``REGCONFIG`` and ``tsvector`` types that
the default ``StrSQLCompiler`` cannot render literally.
"""

from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from decision_hub.infra.database import fetch_similar_skills, search_skills_hybrid


def _compiled_sql_for_call(conn: MagicMock, call_index: int = 0) -> str:
    """Return the compiled SQL string for ``conn.execute`` call ``call_index``."""
    stmt = conn.execute.call_args_list[call_index][0][0]
    return str(stmt.compile(dialect=postgresql.dialect()))


class TestSearchSkillsHybridStableOrder:
    """``search_skills_hybrid`` must emit deterministic ORDER BY for both branches."""

    def test_fts_query_has_tiebreaker_after_rank(self) -> None:
        """When fts_queries is non-empty, ORDER BY fts_rank, slug, name."""
        conn = MagicMock()
        conn.execute.return_value.all.return_value = []

        search_skills_hybrid(
            conn,
            fts_queries=["bayesian"],
            query_embedding=None,
            limit=5,
        )

        compiled = _compiled_sql_for_call(conn)
        # The rank column comes first; (slug, skill name) must follow as tiebreakers.
        assert "ORDER BY" in compiled
        rank_idx = compiled.index("fts_rank DESC")
        slug_idx = compiled.index("organizations.slug", rank_idx)
        name_idx = compiled.index("skills.name", rank_idx)
        assert rank_idx < slug_idx < name_idx, (
            f"Expected fts_rank, organizations.slug, skills.name in ORDER BY:\n{compiled}"
        )

    def test_vector_query_has_tiebreaker_after_distance(self) -> None:
        """When query_embedding is provided, ORDER BY vec_dist, slug, name."""
        conn = MagicMock()
        conn.execute.return_value.all.return_value = []

        search_skills_hybrid(
            conn,
            fts_queries=[],
            query_embedding=[0.0] * 768,
            limit=5,
        )

        compiled = _compiled_sql_for_call(conn)
        assert "ORDER BY" in compiled
        dist_idx = compiled.index("vec_dist ASC")
        slug_idx = compiled.index("organizations.slug", dist_idx)
        name_idx = compiled.index("skills.name", dist_idx)
        assert dist_idx < slug_idx < name_idx, (
            f"Expected vec_dist, organizations.slug, skills.name in ORDER BY:\n{compiled}"
        )


class TestFetchSimilarSkillsStableOrder:
    """``fetch_similar_skills`` runs an embedding lookup then a vector LIMIT query."""

    def test_vector_query_has_tiebreaker_after_distance(self) -> None:
        """The LIMIT-bearing similarity query must include (slug, name) tiebreakers."""
        conn = MagicMock()
        # First call: embedding lookup for the source skill — return a fake row.
        first_row = MagicMock()
        first_row.embedding = [0.0] * 768
        conn.execute.return_value.first.return_value = first_row
        conn.execute.return_value.all.return_value = []

        fetch_similar_skills(conn, "acme", "widget", limit=4)

        # Two execute() calls: lookup + similarity. Inspect the second.
        assert conn.execute.call_count == 2, (
            f"Expected 2 execute calls (lookup + similarity), got {conn.execute.call_count}"
        )
        compiled = _compiled_sql_for_call(conn, call_index=1)
        assert "ORDER BY" in compiled
        dist_idx = compiled.index("vec_dist ASC")
        slug_idx = compiled.index("organizations.slug", dist_idx)
        name_idx = compiled.index("skills.name", dist_idx)
        assert dist_idx < slug_idx < name_idx, (
            f"Expected vec_dist, organizations.slug, skills.name in ORDER BY:\n{compiled}"
        )

    def test_returns_empty_when_skill_has_no_embedding(self) -> None:
        """If the source skill has no embedding, no similarity query is issued."""
        conn = MagicMock()
        conn.execute.return_value.first.return_value = None

        result = fetch_similar_skills(conn, "acme", "widget", limit=4)

        assert result == []
        # Only the embedding lookup ran; the LIMIT query was skipped.
        assert conn.execute.call_count == 1
