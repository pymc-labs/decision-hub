"""DB-layer tests for eval-run query functions.

Covers the behaviour of ``update_eval_run_status`` -- specifically the
``bump_heartbeat`` flag introduced so the API's zombie-sweep write doesn't
inadvertently refresh the heartbeat of the dead worker it's burying.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from sqlalchemy.sql import Update

from decision_hub.infra.database import update_eval_run_status


def _captured_value_keys(conn: MagicMock) -> set[str]:
    """Return the column names targeted by the last UPDATE statement.

    We only need to know *which* columns the UPDATE will write, not their
    bound values, so we read column names off the SQLAlchemy ``Update``
    statement's compiled column set.
    """
    assert conn.execute.call_count == 1
    stmt = conn.execute.call_args.args[0]
    assert isinstance(stmt, Update)
    # ``stmt._values`` keys are the kwargs names passed to ``.values(**...)``,
    # i.e. the bare column names (e.g. "status", "heartbeat_at").
    return {str(key) for key in stmt._values}


class TestUpdateEvalRunStatusBumpHeartbeat:
    """The ``bump_heartbeat`` flag controls whether ``heartbeat_at`` is touched."""

    def test_default_bumps_heartbeat(self) -> None:
        """Workers (the default caller) refresh ``heartbeat_at`` on every write."""
        conn = MagicMock()
        update_eval_run_status(conn, uuid4(), status="running", stage="agent")

        cols = _captured_value_keys(conn)
        assert "heartbeat_at" in cols
        assert "status" in cols
        assert "stage" in cols

    def test_no_bump_skips_heartbeat_column(self) -> None:
        """``bump_heartbeat=False`` keeps ``heartbeat_at`` out of the UPDATE.

        This is what the API's zombie sweep needs: it records the failure
        *without* simultaneously claiming the worker is still alive.
        """
        conn = MagicMock()
        update_eval_run_status(
            conn,
            uuid4(),
            status="failed",
            error_message="Stale heartbeat (400s).",
            completed_at=datetime.now(UTC),
            bump_heartbeat=False,
        )

        cols = _captured_value_keys(conn)
        assert "heartbeat_at" not in cols
        assert "status" in cols
        assert "error_message" in cols
        assert "completed_at" in cols

    def test_no_op_when_nothing_to_update(self) -> None:
        """Passing no fields and ``bump_heartbeat=False`` performs no SQL.

        Prevents wasted no-op UPDATEs that would otherwise fire on every call
        with an empty ``values`` payload.
        """
        conn = MagicMock()
        update_eval_run_status(conn, uuid4(), bump_heartbeat=False)
        conn.execute.assert_not_called()
