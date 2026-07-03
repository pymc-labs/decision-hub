"""Tests for the URL normalization used by tracker + skill-removed queries.

Both `_normalize_repo_url` (Python) and `_normalize_repo_url_sql` (SQL) must
produce the same result for the same input — a pre-existing mismatch let a
skill stored as `https://x/y.git/` fail to match the same repo passed as
`https://x/y`. Regressing that alignment would silently unlink trackers
from their skills, so the test freezes the invariant end-to-end.
"""

import pytest
import sqlalchemy as sa

from decision_hub.infra.database import _normalize_repo_url, _normalize_repo_url_sql


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://github.com/pymc-labs/pymc", "https://github.com/pymc-labs/pymc"),
        ("https://github.com/pymc-labs/pymc.git", "https://github.com/pymc-labs/pymc"),
        ("https://github.com/pymc-labs/pymc/", "https://github.com/pymc-labs/pymc"),
        # The historical bug: `.git/` on the end used to survive normalization
        # because the SQL side stripped `.git$` before the rtrim, so `.git/`
        # wasn't at the end and stayed put.
        ("https://github.com/pymc-labs/pymc.git/", "https://github.com/pymc-labs/pymc"),
        ("https://github.com/pymc-labs/pymc.git//", "https://github.com/pymc-labs/pymc"),
    ],
)
def test_python_normalization_matches_expectations(raw: str, expected: str) -> None:
    assert _normalize_repo_url(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://github.com/pymc-labs/pymc", "https://github.com/pymc-labs/pymc"),
        ("https://github.com/pymc-labs/pymc.git", "https://github.com/pymc-labs/pymc"),
        ("https://github.com/pymc-labs/pymc/", "https://github.com/pymc-labs/pymc"),
        ("https://github.com/pymc-labs/pymc.git/", "https://github.com/pymc-labs/pymc"),
    ],
)
def test_sql_normalization_matches_python(raw: str, expected: str) -> None:
    """Compile the SQL expression and verify SQLite's runtime produces the
    same string as the Python helper — that's the invariant that used to
    drift between the two implementations."""
    engine = sa.create_engine("sqlite:///:memory:")
    # SQLite doesn't know about regexp_replace by default; register a Python
    # UDF that uses `re.sub` and matches Postgres semantics for our needs.
    import re

    @sa.event.listens_for(engine, "connect")
    def _register_regexp_replace(dbapi_conn, _rec):
        dbapi_conn.create_function("regexp_replace", 3, lambda s, p, r: re.sub(p, r, s or ""))

    with engine.connect() as conn:
        col = sa.literal(raw)
        result = conn.execute(sa.select(_normalize_repo_url_sql(col))).scalar_one()
    assert result == expected
    # And matches the Python side.
    assert result == _normalize_repo_url(raw)
