"""Regression tests: every LIMIT-bounded query must have a deterministic ORDER BY.

CLAUDE.md lists this as a project-wide invariant ("Every query with
LIMIT must have an explicit ORDER BY with a unique tiebreaker").
Non-deterministic top-N results cause flaky pagination, misleading
similar-skill rankings, and version drift during publish races.

These tests assert on compiled SQL shape to avoid needing a live DB.
"""

from unittest.mock import MagicMock
from uuid import uuid4

from decision_hub.infra.database import (
    _refresh_skill_latest_version,
    fetch_similar_skills,
)


class TestFetchSimilarSkillsOrdering:
    def test_orders_by_vec_dist_then_id_tiebreaker(self):
        """Similar-skill vector search needs a tiebreaker on skills.id so
        two candidates with identical cosine distance yield a
        deterministic top-N across replicas."""
        mock_conn = MagicMock()
        # Pretend the queried skill has an embedding; return a dummy vector.
        first_call_result = MagicMock()
        first_call_result.embedding = [0.1] * 1536
        mock_conn.execute.return_value.first.return_value = first_call_result
        # Second call returns no rows (we only care about SQL shape).
        mock_conn.execute.return_value.all.return_value = []

        fetch_similar_skills(mock_conn, "myorg", "skill-a", limit=5)

        # The second call is the vector-ordered query.
        vec_call = mock_conn.execute.call_args_list[-1]
        compiled = str(vec_call[0][0])
        assert "ORDER BY" in compiled
        assert "vec_dist ASC" in compiled
        # Tiebreaker: skills.id ASC so ties are broken the same way everywhere.
        assert "skills.id ASC" in compiled


class TestRefreshSkillLatestVersionOrdering:
    def test_orders_by_semver_parts_with_id_tiebreaker(self):
        """Denormalized latest-version refresh orders by (major, minor,
        patch) DESC but must also include an id DESC tiebreaker — two
        rows accidentally sharing a triple would otherwise pick an
        arbitrary winner, causing denormalized columns to flap."""
        mock_conn = MagicMock()
        # Return no rows — we only inspect the SELECT shape.
        mock_conn.execute.return_value.first.return_value = None

        _refresh_skill_latest_version(mock_conn, uuid4())

        first_call = mock_conn.execute.call_args_list[0]
        compiled = str(first_call[0][0])
        assert "ORDER BY" in compiled
        assert "semver_major DESC" in compiled
        assert "semver_minor DESC" in compiled
        assert "semver_patch DESC" in compiled
        assert "versions.id DESC" in compiled
        assert "LIMIT" in compiled
