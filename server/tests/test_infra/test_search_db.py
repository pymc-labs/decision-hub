"""Tests for SQL correctness of the search / similarity DB queries.

These are compile-level tests (no live DB) that verify each `LIMIT` query has
a unique `ORDER BY` tiebreaker per the project's "SQL query correctness"
convention. Without the tiebreaker, two rows with identical rank/distance
produce non-deterministic pagination and can be silently dropped or
duplicated between calls.
"""

from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql

from decision_hub.infra.database import (
    fetch_similar_skills,
    find_active_eval_runs_for_user,
    search_skills_hybrid,
)


def _compile(stmt) -> str:
    # Compile against the postgres dialect so pgvector / REGCONFIG-typed
    # literals render. We only need the SQL text for substring assertions,
    # not to execute the statement.
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False})).lower()


def _make_conn_returning(rows: list) -> MagicMock:
    conn = MagicMock()
    conn.execute.return_value.all.return_value = rows
    conn.execute.return_value.first.return_value = None
    return conn


class TestSearchSkillsHybridTiebreakers:
    """Both FTS and vector branches must include a unique tiebreaker."""

    def test_fts_order_by_includes_id_desc(self) -> None:
        conn = _make_conn_returning([])
        search_skills_hybrid(
            conn,
            fts_queries=["hello world"],
            query_embedding=None,
            limit=5,
        )
        sql = _compile(conn.execute.call_args_list[0].args[0])
        assert "order by fts_rank desc" in sql
        # The `skills.id DESC` tiebreaker prevents ts_rank_cd ties (zero-rank
        # keyword misses, identical documents) producing unstable pagination.
        assert "skills.id desc" in sql

    def test_vector_order_by_includes_id_desc(self) -> None:
        conn = _make_conn_returning([])
        search_skills_hybrid(
            conn,
            fts_queries=[],
            query_embedding=[0.0] * 768,
            limit=5,
        )
        sql = _compile(conn.execute.call_args_list[0].args[0])
        assert "order by vec_dist asc" in sql
        # `skills.id DESC` guards against identical embeddings (forks,
        # duplicate content) producing unstable top-K.
        assert "skills.id desc" in sql


class TestFetchSimilarSkills:
    """`fetch_similar_skills` should run one query (CTE) and include a tiebreaker."""

    def test_single_round_trip_and_includes_tiebreaker(self) -> None:
        # Return a row with an embedding so the CTE path is exercised.
        conn = MagicMock()
        conn.execute.return_value.all.return_value = []

        fetch_similar_skills(conn, "acme", "greeter", limit=5)

        # The refactor collapses the previous two-query pattern into one
        # statement using a CTE. Assert exactly one execute() call.
        assert conn.execute.call_count == 1
        sql = _compile(conn.execute.call_args_list[0].args[0])
        assert "order by vec_dist asc" in sql
        assert "skills.id desc" in sql


class TestFindActiveEvalRunsTiebreaker:
    def test_order_by_includes_id_desc(self) -> None:
        from uuid import uuid4

        conn = _make_conn_returning([])
        find_active_eval_runs_for_user(conn, uuid4(), limit=10)
        sql = _compile(conn.execute.call_args_list[0].args[0])
        assert "created_at desc" in sql
        # Two eval runs created in the same millisecond (parallel `dhub
        # publish` invocations) must order deterministically.
        assert "id desc" in sql
