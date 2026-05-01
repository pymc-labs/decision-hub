"""Regression tests for fetch_similar_skills query construction.

CLAUDE.md: every query with LIMIT must have an explicit ORDER BY with a
unique tiebreaker. Tied embedding distances are common (forks, near-duplicate
descriptions) and without (slug, name) on the ORDER BY clause the LIMIT
slices an arbitrary subset and re-runs return different rows.
"""

from unittest.mock import MagicMock

import sqlalchemy as sa

from decision_hub.infra.database import fetch_similar_skills


def _captured_vec_select(mock_conn: MagicMock) -> sa.Select:
    """Return the second ``execute`` argument: the vector-search statement.

    The first call fetches the source embedding; the second runs the actual
    similarity search. Both are issued as positional args.
    """
    assert mock_conn.execute.call_count >= 2, "expected source-embedding then vector-search calls"
    return mock_conn.execute.call_args_list[1][0][0]


def test_orders_by_distance_and_unique_tiebreaker() -> None:
    """The vector-similarity SELECT must order by (vec_dist, slug, name).

    Without the trailing (slug, name) the LIMIT result is non-deterministic
    when multiple skills share an embedding distance.
    """
    mock_conn = MagicMock()

    # First call — fetch source embedding. Return a row with a non-null
    # embedding so the function proceeds to issue the vector-search query.
    src_row = MagicMock()
    src_row.embedding = [0.1] * 8

    # Second call — vector-search. We don't care about its results, only
    # that the SELECT we passed in had the right ORDER BY.
    vec_result = MagicMock()
    vec_result.all.return_value = []

    mock_conn.execute.side_effect = [
        MagicMock(first=MagicMock(return_value=src_row)),
        vec_result,
    ]

    fetch_similar_skills(mock_conn, "acme", "widget", limit=5)

    stmt = _captured_vec_select(mock_conn)
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": False})).lower()

    # Each tiebreaker must appear in the ORDER BY clause. The exact ordering
    # is asserted via index comparison so a future refactor cannot move the
    # primary distance after the tiebreakers.
    assert "order by" in compiled, compiled
    order_clause = compiled.split("order by", 1)[1]
    vec_pos = order_clause.find("vec_dist")
    slug_pos = order_clause.find("organizations.slug")
    name_pos = order_clause.find("skills.name")
    assert vec_pos >= 0, f"missing vec_dist in: {order_clause}"
    assert slug_pos > vec_pos, f"slug must follow vec_dist: {order_clause}"
    assert name_pos > slug_pos, f"name must follow slug: {order_clause}"


def test_returns_empty_when_skill_has_no_embedding() -> None:
    """A skill without a stored embedding short-circuits to an empty list.

    Documents existing behaviour and guards against accidental query
    issuance for missing embeddings.
    """
    mock_conn = MagicMock()
    src_row = MagicMock()
    src_row.embedding = None
    mock_conn.execute.return_value = MagicMock(first=MagicMock(return_value=src_row))

    out = fetch_similar_skills(mock_conn, "acme", "widget", limit=5)

    assert out == []
    # Only the source-embedding probe should have run; no vector query.
    assert mock_conn.execute.call_count == 1
