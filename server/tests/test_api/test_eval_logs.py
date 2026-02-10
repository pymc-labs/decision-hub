"""Tests for eval run and log streaming endpoints.

Covers:
- GET /v1/eval-runs/{run_id} — run metadata and zombie detection
- GET /v1/eval-runs/{run_id}/logs — cursor-based event pagination
- GET /v1/eval-runs — listing runs
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from decision_hub.models import EvalRun

SAMPLE_USER_ID = UUID("12345678-1234-5678-1234-567812345678")


def _make_eval_run(**overrides) -> EvalRun:
    """Create an EvalRun with sensible defaults, overridable per field."""
    defaults = {
        "id": uuid4(),
        "version_id": uuid4(),
        "user_id": SAMPLE_USER_ID,
        "agent": "claude",
        "judge_model": "claude-sonnet-4-5-20250929",
        "status": "running",
        "stage": "agent",
        "current_case": "test-case",
        "current_case_index": 0,
        "total_cases": 2,
        "heartbeat_at": datetime.now(UTC),
        "log_s3_prefix": "eval-logs/test-run/",
        "log_seq": 3,
        "error_message": None,
        "created_at": datetime.now(UTC),
        "completed_at": None,
    }
    defaults.update(overrides)
    return EvalRun(**defaults)


# ---------------------------------------------------------------------------
# GET /v1/eval-runs/{run_id} — run metadata
# ---------------------------------------------------------------------------


class TestGetEvalRun:
    """GET /v1/eval-runs/{run_id} — run metadata and zombie detection."""

    @patch("decision_hub.api.registry_routes.find_eval_run")
    def test_returns_run_metadata(
        self,
        mock_find_run: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        run = _make_eval_run(status="running", stage="agent")
        mock_find_run.return_value = run

        resp = client.get(f"/v1/eval-runs/{run.id}", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(run.id)
        assert data["status"] == "running"
        assert data["stage"] == "agent"
        assert data["agent"] == "claude"
        assert data["total_cases"] == 2

    @patch("decision_hub.api.registry_routes.find_eval_run")
    def test_not_found(
        self,
        mock_find_run: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_find_run.return_value = None

        resp = client.get(f"/v1/eval-runs/{uuid4()}", headers=auth_headers)

        assert resp.status_code == 404

    @patch("decision_hub.api.registry_routes.update_eval_run_status")
    @patch("decision_hub.api.registry_routes.find_eval_run")
    def test_zombie_detection_marks_stale_run_as_failed(
        self,
        mock_find_run: MagicMock,
        mock_update_status: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """A running eval with a heartbeat >5 min stale is marked failed."""
        stale_heartbeat = datetime.now(UTC) - timedelta(seconds=400)
        run = _make_eval_run(status="running", heartbeat_at=stale_heartbeat)

        # find_eval_run is called twice: once before zombie check, once after
        failed_run = _make_eval_run(
            id=run.id,
            status="failed",
            error_message="Stale heartbeat",
            heartbeat_at=stale_heartbeat,
        )
        mock_find_run.side_effect = [run, failed_run]

        resp = client.get(f"/v1/eval-runs/{run.id}", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"
        mock_update_status.assert_called_once()
        call_kwargs = mock_update_status.call_args
        assert call_kwargs.kwargs.get("status") == "failed"

    @patch("decision_hub.api.registry_routes.update_eval_run_status")
    @patch("decision_hub.api.registry_routes.find_eval_run")
    def test_fresh_heartbeat_not_marked_zombie(
        self,
        mock_find_run: MagicMock,
        mock_update_status: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """A running eval with a recent heartbeat is NOT marked failed."""
        run = _make_eval_run(
            status="running",
            heartbeat_at=datetime.now(UTC) - timedelta(seconds=30),
        )
        mock_find_run.return_value = run

        resp = client.get(f"/v1/eval-runs/{run.id}", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        mock_update_status.assert_not_called()

    @patch("decision_hub.api.registry_routes.find_eval_run")
    def test_completed_run_not_checked_for_zombie(
        self,
        mock_find_run: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Completed runs skip zombie detection regardless of heartbeat age."""
        old_heartbeat = datetime.now(UTC) - timedelta(seconds=9999)
        run = _make_eval_run(
            status="completed",
            heartbeat_at=old_heartbeat,
            completed_at=datetime.now(UTC),
        )
        mock_find_run.return_value = run

        resp = client.get(f"/v1/eval-runs/{run.id}", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"


# ---------------------------------------------------------------------------
# GET /v1/eval-runs/{run_id}/logs — cursor-based event pagination
# ---------------------------------------------------------------------------


class TestGetEvalRunLogs:
    """GET /v1/eval-runs/{run_id}/logs — cursor-based event pagination."""

    @patch("decision_hub.api.registry_routes.read_eval_log_chunk")
    @patch("decision_hub.api.registry_routes.list_eval_log_chunks")
    @patch("decision_hub.api.registry_routes.find_eval_run")
    def test_cursor_filters_events_not_chunks(
        self,
        mock_find_run: MagicMock,
        mock_list_chunks: MagicMock,
        mock_read_chunk: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Cursor is an event seq number, not a chunk file number.

        Regression test: previously the cursor was passed to list_eval_log_chunks
        which filtered by chunk file seq (1, 2, 3) instead of event seq (1..N).
        After the first poll returned events, cursor jumped past all chunk file
        numbers, causing all subsequent polls to return 0 events.
        """
        run = _make_eval_run()
        mock_find_run.return_value = run

        mock_list_chunks.return_value = [
            (1, "eval-logs/test-run/0001.jsonl"),
            (2, "eval-logs/test-run/0002.jsonl"),
            (3, "eval-logs/test-run/0003.jsonl"),
        ]

        # Chunk 1: events 1-3, Chunk 2: events 4-6, Chunk 3: events 7-9
        mock_read_chunk.side_effect = [
            '{"seq":1,"type":"setup","content":"init"}\n'
            '{"seq":2,"type":"case_start","case_name":"a"}\n'
            '{"seq":3,"type":"log","content":"hello"}\n',
            '{"seq":4,"type":"log","content":"world"}\n'
            '{"seq":5,"type":"judge_start"}\n'
            '{"seq":6,"type":"case_result","verdict":"pass"}\n',
            '{"seq":7,"type":"case_start","case_name":"b"}\n'
            '{"seq":8,"type":"log","content":"test"}\n'
            '{"seq":9,"type":"case_result","verdict":"pass"}\n',
        ]

        resp = client.get(
            f"/v1/eval-runs/{run.id}/logs?cursor=5",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        event_seqs = [e["seq"] for e in data["events"]]
        assert event_seqs == [6, 7, 8, 9]
        assert data["next_cursor"] == 9

    @patch("decision_hub.api.registry_routes.read_eval_log_chunk")
    @patch("decision_hub.api.registry_routes.list_eval_log_chunks")
    @patch("decision_hub.api.registry_routes.find_eval_run")
    def test_cursor_zero_returns_all_events(
        self,
        mock_find_run: MagicMock,
        mock_list_chunks: MagicMock,
        mock_read_chunk: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        run = _make_eval_run()
        mock_find_run.return_value = run
        mock_list_chunks.return_value = [
            (1, "eval-logs/test-run/0001.jsonl"),
        ]
        mock_read_chunk.return_value = (
            '{"seq":1,"type":"setup","content":"init"}\n{"seq":2,"type":"case_start","case_name":"a"}\n'
        )

        resp = client.get(
            f"/v1/eval-runs/{run.id}/logs?cursor=0",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["events"]) == 2
        assert data["next_cursor"] == 2

    @patch("decision_hub.api.registry_routes.list_eval_log_chunks")
    @patch("decision_hub.api.registry_routes.find_eval_run")
    def test_no_chunks_returns_empty_events(
        self,
        mock_find_run: MagicMock,
        mock_list_chunks: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """When no S3 chunks exist yet, returns empty events with cursor unchanged."""
        run = _make_eval_run(status="provisioning")
        mock_find_run.return_value = run
        mock_list_chunks.return_value = []

        resp = client.get(
            f"/v1/eval-runs/{run.id}/logs?cursor=0",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["events"] == []
        assert data["next_cursor"] == 0
        assert data["run_status"] == "provisioning"

    @patch("decision_hub.api.registry_routes.read_eval_log_chunk")
    @patch("decision_hub.api.registry_routes.list_eval_log_chunks")
    @patch("decision_hub.api.registry_routes.find_eval_run")
    def test_cursor_past_all_events_returns_empty(
        self,
        mock_find_run: MagicMock,
        mock_list_chunks: MagicMock,
        mock_read_chunk: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Cursor beyond the max event seq returns no new events."""
        run = _make_eval_run()
        mock_find_run.return_value = run
        mock_list_chunks.return_value = [
            (1, "eval-logs/test-run/0001.jsonl"),
        ]
        mock_read_chunk.return_value = '{"seq":1,"type":"setup","content":"init"}\n'

        resp = client.get(
            f"/v1/eval-runs/{run.id}/logs?cursor=99",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["events"] == []
        assert data["next_cursor"] == 99

    @patch("decision_hub.api.registry_routes.read_eval_log_chunk")
    @patch("decision_hub.api.registry_routes.list_eval_log_chunks")
    @patch("decision_hub.api.registry_routes.find_eval_run")
    def test_includes_run_status_and_stage(
        self,
        mock_find_run: MagicMock,
        mock_list_chunks: MagicMock,
        mock_read_chunk: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Response includes current run status, stage, and case for progress rendering."""
        run = _make_eval_run(
            status="judging",
            stage="judge",
            current_case="convergence-diagnostics",
        )
        mock_find_run.return_value = run
        mock_list_chunks.return_value = [(1, "eval-logs/test-run/0001.jsonl")]
        mock_read_chunk.return_value = '{"seq":1,"type":"setup","content":"init"}\n'

        resp = client.get(
            f"/v1/eval-runs/{run.id}/logs?cursor=0",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["run_status"] == "judging"
        assert data["run_stage"] == "judge"
        assert data["current_case"] == "convergence-diagnostics"

    @patch("decision_hub.api.registry_routes.find_eval_run")
    def test_logs_not_found(
        self,
        mock_find_run: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_find_run.return_value = None

        resp = client.get(
            f"/v1/eval-runs/{uuid4()}/logs?cursor=0",
            headers=auth_headers,
        )

        assert resp.status_code == 404

    @patch("decision_hub.api.registry_routes.update_eval_run_status")
    @patch("decision_hub.api.registry_routes.list_eval_log_chunks")
    @patch("decision_hub.api.registry_routes.find_eval_run")
    def test_zombie_detected_during_log_fetch(
        self,
        mock_find_run: MagicMock,
        mock_list_chunks: MagicMock,
        mock_update_status: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        """Stale heartbeat during log fetch triggers zombie detection."""
        stale_heartbeat = datetime.now(UTC) - timedelta(seconds=400)
        run = _make_eval_run(status="running", heartbeat_at=stale_heartbeat)
        mock_find_run.return_value = run
        mock_list_chunks.return_value = []

        resp = client.get(
            f"/v1/eval-runs/{run.id}/logs?cursor=0",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["run_status"] == "failed"
        mock_update_status.assert_called_once()


# ---------------------------------------------------------------------------
# GET /v1/eval-runs — list runs
# ---------------------------------------------------------------------------


class TestListEvalRuns:
    """GET /v1/eval-runs — list eval runs."""

    @patch("decision_hub.api.registry_routes.find_active_eval_runs_for_user")
    def test_list_runs_for_user(
        self,
        mock_find_runs: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        run = _make_eval_run(status="completed")
        mock_find_runs.return_value = [run]

        resp = client.get("/v1/eval-runs", headers=auth_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == str(run.id)

    @patch("decision_hub.api.registry_routes.find_eval_runs_for_version")
    def test_list_runs_by_version_id(
        self,
        mock_find_runs: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        version_id = uuid4()
        run = _make_eval_run(version_id=version_id)
        mock_find_runs.return_value = [run]

        resp = client.get(
            f"/v1/eval-runs?version_id={version_id}",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["version_id"] == str(version_id)

    @patch("decision_hub.api.registry_routes.find_active_eval_runs_for_user")
    def test_list_runs_empty(
        self,
        mock_find_runs: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ) -> None:
        mock_find_runs.return_value = []

        resp = client.get("/v1/eval-runs", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json() == []
