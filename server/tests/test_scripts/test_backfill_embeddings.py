"""Tests for decision_hub.scripts.backfill_embeddings.

Focused on the SQL correctness rule: every LIMIT query must have an
explicit ORDER BY with a unique tiebreaker (see CLAUDE.md).
"""

from decision_hub.infra.database import skills_table
from decision_hub.scripts import backfill_embeddings as backfill_mod


def test_backfill_query_orders_by_id_before_limit() -> None:
    """The batch-fetch SELECT must order by a unique column before LIMIT.

    Regression: without ORDER BY, a batch that fails and gets retried
    can hit a different set of rows (Postgres is free to reorder), which
    combined with the circuit-breaker loop caused hot-looping on the
    same failing rows.

    We inspect the SQLAlchemy select() built inside ``backfill`` by
    running it against a stubbed engine/connection and capturing the
    compiled statement. This is easier than mocking the whole run loop.
    """
    captured: dict[str, str] = {}

    class _StubResult:
        def all(self) -> list:
            return []

    class _StubConn:
        def __enter__(self) -> "_StubConn":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def execute(self, stmt) -> _StubResult:
            captured["sql"] = str(stmt.compile(compile_kwargs={"literal_binds": True}))
            return _StubResult()

        def commit(self) -> None:
            pass

    class _StubEngine:
        def connect(self) -> _StubConn:
            return _StubConn()

    class _StubSettings:
        database_url = "postgresql://ignored"

    def _stub_create_engine(_url: str) -> _StubEngine:
        return _StubEngine()

    def _stub_create_settings(*_a: object, **_kw: object) -> _StubSettings:
        return _StubSettings()

    def _stub_create_embedding_client(_settings: object) -> tuple[dict, str]:
        return {}, "gemini-embedding-001"

    orig_create_engine = backfill_mod.create_engine
    orig_create_client = backfill_mod.create_embedding_client
    orig_create_settings = backfill_mod.create_settings
    backfill_mod.create_engine = _stub_create_engine
    backfill_mod.create_embedding_client = _stub_create_embedding_client
    backfill_mod.create_settings = _stub_create_settings
    try:
        backfill_mod.backfill(batch_size=10)
    finally:
        backfill_mod.create_engine = orig_create_engine
        backfill_mod.create_embedding_client = orig_create_client
        backfill_mod.create_settings = orig_create_settings

    sql = captured["sql"]
    # LIMIT must appear AFTER an ORDER BY on the unique id column.
    assert "ORDER BY" in sql.upper()
    order_pos = sql.upper().find("ORDER BY")
    limit_pos = sql.upper().find("LIMIT")
    assert 0 < order_pos < limit_pos, sql
    assert str(skills_table.c.id) in sql
