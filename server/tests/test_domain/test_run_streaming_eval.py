"""Tests for run_streaming_eval() — the DB+S3 integration layer.

run_streaming_eval() is the most complex function in the eval pipeline:
it consumes the streaming generator, batches events, flushes to S3,
updates DB heartbeats, and writes the final eval_reports row.

Note: run_streaming_eval uses lazy imports (inside the function body),
so patches target the source modules (decision_hub.infra.database,
decision_hub.infra.storage) rather than decision_hub.domain.evals.
"""

import json
from unittest.mock import MagicMock, call, patch
from uuid import uuid4

import pytest

from decision_hub.domain.evals import run_streaming_eval
from decision_hub.models import EvalCase, EvalConfig


def _make_config() -> EvalConfig:
    return EvalConfig(agent="claude", judge_model="claude-sonnet-4-5-20250929")


def _make_cases(n: int = 1) -> tuple[EvalCase, ...]:
    return tuple(
        EvalCase(
            name=f"case-{i}",
            description=f"Test case {i}",
            prompt=f"Run test {i}",
            judge_criteria=f"PASS: case {i} produces output\nFAIL: crashes",
        )
        for i in range(n)
    )


def _make_mock_engine():
    """Create a mock SQLAlchemy engine with working connect() context manager."""
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_conn
    return mock_engine, mock_conn


# Patches target the source modules because run_streaming_eval uses
# lazy imports: `from decision_hub.infra.database import create_engine`
_P_CREATE_ENGINE = "decision_hub.infra.database.create_engine"
_P_INSERT_REPORT = "decision_hub.infra.database.insert_eval_report"
_P_UPDATE_STATUS = "decision_hub.infra.database.update_eval_run_status"
_P_UPLOAD_CHUNK = "decision_hub.infra.storage.upload_eval_log_chunk"
_P_PIPELINE = "decision_hub.domain.evals.stream_eval_pipeline"


class TestRunStreamingEval:
    """Tests for the run_streaming_eval() orchestrator."""

    @patch(_P_UPLOAD_CHUNK)
    @patch(_P_UPDATE_STATUS)
    @patch(_P_INSERT_REPORT)
    @patch(_P_CREATE_ENGINE)
    @patch(_P_PIPELINE)
    def test_happy_path_writes_report_and_completes(
        self,
        mock_pipeline: MagicMock,
        mock_create_engine: MagicMock,
        mock_insert_report: MagicMock,
        mock_update_status: MagicMock,
        mock_upload_chunk: MagicMock,
    ):
        """Successful pipeline: events flushed to S3, report written, run marked completed."""
        mock_engine, mock_conn = _make_mock_engine()
        mock_create_engine.return_value = mock_engine

        run_id = uuid4()
        version_id = uuid4()

        mock_pipeline.return_value = iter(
            [
                {"seq": 1, "type": "setup", "ts": "t1", "content": "Starting"},
                {"seq": 2, "type": "case_start", "ts": "t2", "case_index": 0, "case_name": "case-0", "total_cases": 1},
                {"seq": 3, "type": "log", "ts": "t3", "stream": "stdout", "content": "output"},
                {"seq": 4, "type": "judge_start", "ts": "t4", "case_index": 0, "case_name": "case-0"},
                {
                    "seq": 5,
                    "type": "case_result",
                    "ts": "t5",
                    "case_index": 0,
                    "case_name": "case-0",
                    "verdict": "pass",
                    "reasoning": "Good",
                    "duration_ms": 5000,
                },
                {
                    "seq": 6,
                    "type": "report",
                    "ts": "t6",
                    "passed": 1,
                    "total": 1,
                    "status": "completed",
                    "total_duration_ms": 5000,
                    "case_results": [
                        {
                            "name": "case-0",
                            "description": "Test case 0",
                            "verdict": "pass",
                            "reasoning": "Good",
                            "agent_output": "output",
                            "agent_stderr": "",
                            "exit_code": 0,
                            "duration_ms": 5000,
                            "stage": "judge",
                        }
                    ],
                },
            ]
        )

        run_streaming_eval(
            run_id=run_id,
            version_id=version_id,
            skill_zip=b"fake-zip",
            eval_config=_make_config(),
            eval_cases=_make_cases(1),
            agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
            org_slug="test-org",
            skill_name="test-skill",
            judge_api_key="judge-key",
            database_url="postgresql://test",
            s3_client=MagicMock(),
            s3_bucket="test-bucket",
            log_s3_prefix=f"eval-logs/{run_id}/",
        )

        # Verify provisioning status set first
        status_calls = mock_update_status.call_args_list
        assert status_calls[0] == call(mock_conn, run_id, status="provisioning", stage="setup")

        # Verify eval report was inserted
        mock_insert_report.assert_called_once()
        report_kwargs = mock_insert_report.call_args
        assert report_kwargs.kwargs["version_id"] == version_id
        assert report_kwargs.kwargs["passed"] == 1
        assert report_kwargs.kwargs["total"] == 1
        assert report_kwargs.kwargs["status"] == "completed"

        # Verify final status update marks run as completed
        completed_calls = [c for c in status_calls if c.kwargs.get("status") == "completed"]
        assert len(completed_calls) >= 1

        # Verify at least one S3 chunk was uploaded (final flush)
        assert mock_upload_chunk.call_count >= 1

    @patch(_P_UPLOAD_CHUNK)
    @patch(_P_UPDATE_STATUS)
    @patch(_P_INSERT_REPORT)
    @patch(_P_CREATE_ENGINE)
    @patch(_P_PIPELINE)
    def test_pipeline_exception_marks_run_as_failed(
        self,
        mock_pipeline: MagicMock,
        mock_create_engine: MagicMock,
        mock_insert_report: MagicMock,
        mock_update_status: MagicMock,
        mock_upload_chunk: MagicMock,
    ):
        """Pipeline crash: run is marked failed in DB, exception re-raised."""
        mock_engine, _mock_conn = _make_mock_engine()
        mock_create_engine.return_value = mock_engine

        run_id = uuid4()

        mock_pipeline.side_effect = RuntimeError("Sandbox provisioning failed")

        with pytest.raises(RuntimeError, match="Sandbox provisioning failed"):
            run_streaming_eval(
                run_id=run_id,
                version_id=uuid4(),
                skill_zip=b"fake-zip",
                eval_config=_make_config(),
                eval_cases=_make_cases(1),
                agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
                org_slug="test-org",
                skill_name="test-skill",
                judge_api_key="judge-key",
                database_url="postgresql://test",
                s3_client=MagicMock(),
                s3_bucket="test-bucket",
                log_s3_prefix=f"eval-logs/{run_id}/",
            )

        # Should mark run as failed
        failed_calls = [c for c in mock_update_status.call_args_list if c.kwargs.get("status") == "failed"]
        assert len(failed_calls) >= 1
        assert failed_calls[-1].kwargs.get("error_message") == "Sandbox provisioning failed"
        assert failed_calls[-1].kwargs.get("completed_at") is not None

        # Report should NOT be inserted (pipeline never produced a report event)
        mock_insert_report.assert_not_called()

    @patch(_P_UPLOAD_CHUNK)
    @patch(_P_UPDATE_STATUS)
    @patch(_P_INSERT_REPORT)
    @patch(_P_CREATE_ENGINE)
    @patch(_P_PIPELINE)
    def test_failed_cases_set_status_to_failed(
        self,
        mock_pipeline: MagicMock,
        mock_create_engine: MagicMock,
        mock_insert_report: MagicMock,
        mock_update_status: MagicMock,
        mock_upload_chunk: MagicMock,
    ):
        """When all cases fail, the eval report and run status should be 'failed'."""
        mock_engine, _mock_conn = _make_mock_engine()
        mock_create_engine.return_value = mock_engine

        run_id = uuid4()
        version_id = uuid4()

        mock_pipeline.return_value = iter(
            [
                {"seq": 1, "type": "setup", "ts": "t1", "content": "Starting"},
                {"seq": 2, "type": "case_start", "ts": "t2", "case_index": 0, "case_name": "case-0", "total_cases": 1},
                {
                    "seq": 3,
                    "type": "case_result",
                    "ts": "t3",
                    "case_index": 0,
                    "case_name": "case-0",
                    "verdict": "error",
                    "reasoning": "Sandbox error: OOM",
                    "duration_ms": 0,
                },
                {
                    "seq": 4,
                    "type": "report",
                    "ts": "t4",
                    "passed": 0,
                    "total": 1,
                    "status": "failed",
                    "total_duration_ms": 0,
                    "case_results": [
                        {
                            "name": "case-0",
                            "description": "Test case 0",
                            "verdict": "error",
                            "reasoning": "Sandbox error: OOM",
                            "agent_output": "",
                            "agent_stderr": "",
                            "exit_code": -1,
                            "duration_ms": 0,
                            "stage": "sandbox",
                        }
                    ],
                },
            ]
        )

        run_streaming_eval(
            run_id=run_id,
            version_id=version_id,
            skill_zip=b"fake-zip",
            eval_config=_make_config(),
            eval_cases=_make_cases(1),
            agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
            org_slug="test-org",
            skill_name="test-skill",
            judge_api_key="judge-key",
            database_url="postgresql://test",
            s3_client=MagicMock(),
            s3_bucket="test-bucket",
            log_s3_prefix=f"eval-logs/{run_id}/",
        )

        # Report should be inserted with status=failed
        mock_insert_report.assert_called_once()
        assert mock_insert_report.call_args.kwargs["status"] == "failed"
        assert mock_insert_report.call_args.kwargs["passed"] == 0

    @patch(_P_UPLOAD_CHUNK)
    @patch(_P_UPDATE_STATUS)
    @patch(_P_INSERT_REPORT)
    @patch(_P_CREATE_ENGINE)
    @patch(_P_PIPELINE)
    def test_case_start_triggers_status_update(
        self,
        mock_pipeline: MagicMock,
        mock_create_engine: MagicMock,
        mock_insert_report: MagicMock,
        mock_update_status: MagicMock,
        mock_upload_chunk: MagicMock,
    ):
        """case_start events trigger DB status updates with case name and index."""
        mock_engine, _mock_conn = _make_mock_engine()
        mock_create_engine.return_value = mock_engine

        run_id = uuid4()

        mock_pipeline.return_value = iter(
            [
                {"seq": 1, "type": "setup", "ts": "t1", "content": "Starting"},
                {"seq": 2, "type": "case_start", "ts": "t2", "case_index": 0, "case_name": "case-0", "total_cases": 1},
                {
                    "seq": 3,
                    "type": "report",
                    "ts": "t3",
                    "passed": 0,
                    "total": 1,
                    "status": "failed",
                    "total_duration_ms": 0,
                    "case_results": [],
                },
            ]
        )

        run_streaming_eval(
            run_id=run_id,
            version_id=uuid4(),
            skill_zip=b"fake-zip",
            eval_config=_make_config(),
            eval_cases=_make_cases(1),
            agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
            org_slug="test-org",
            skill_name="test-skill",
            judge_api_key="judge-key",
            database_url="postgresql://test",
            s3_client=MagicMock(),
            s3_bucket="test-bucket",
            log_s3_prefix=f"eval-logs/{run_id}/",
        )

        # Find the case_start heartbeat call
        case_start_calls = [c for c in mock_update_status.call_args_list if c.kwargs.get("current_case") == "case-0"]
        assert len(case_start_calls) == 1
        assert case_start_calls[0].kwargs["status"] == "running"
        assert case_start_calls[0].kwargs["stage"] == "agent"
        assert case_start_calls[0].kwargs["current_case_index"] == 0

    @patch(_P_UPLOAD_CHUNK)
    @patch(_P_UPDATE_STATUS)
    @patch(_P_INSERT_REPORT)
    @patch(_P_CREATE_ENGINE)
    @patch(_P_PIPELINE)
    def test_judge_start_triggers_judging_status(
        self,
        mock_pipeline: MagicMock,
        mock_create_engine: MagicMock,
        mock_insert_report: MagicMock,
        mock_update_status: MagicMock,
        mock_upload_chunk: MagicMock,
    ):
        """judge_start events trigger DB status update to 'judging'."""
        mock_engine, _mock_conn = _make_mock_engine()
        mock_create_engine.return_value = mock_engine

        run_id = uuid4()

        mock_pipeline.return_value = iter(
            [
                {"seq": 1, "type": "setup", "ts": "t1", "content": "Starting"},
                {"seq": 2, "type": "case_start", "ts": "t2", "case_index": 0, "case_name": "case-0", "total_cases": 1},
                {"seq": 3, "type": "judge_start", "ts": "t3", "case_index": 0, "case_name": "case-0"},
                {
                    "seq": 4,
                    "type": "report",
                    "ts": "t4",
                    "passed": 0,
                    "total": 1,
                    "status": "failed",
                    "total_duration_ms": 0,
                    "case_results": [],
                },
            ]
        )

        run_streaming_eval(
            run_id=run_id,
            version_id=uuid4(),
            skill_zip=b"fake-zip",
            eval_config=_make_config(),
            eval_cases=_make_cases(1),
            agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
            org_slug="test-org",
            skill_name="test-skill",
            judge_api_key="judge-key",
            database_url="postgresql://test",
            s3_client=MagicMock(),
            s3_bucket="test-bucket",
            log_s3_prefix=f"eval-logs/{run_id}/",
        )

        judging_calls = [c for c in mock_update_status.call_args_list if c.kwargs.get("status") == "judging"]
        assert len(judging_calls) == 1
        assert judging_calls[0].kwargs["stage"] == "judge"

    @patch(_P_UPLOAD_CHUNK)
    @patch(_P_UPDATE_STATUS)
    @patch(_P_INSERT_REPORT)
    @patch(_P_CREATE_ENGINE)
    @patch(_P_PIPELINE)
    def test_events_buffered_and_flushed_to_s3(
        self,
        mock_pipeline: MagicMock,
        mock_create_engine: MagicMock,
        mock_insert_report: MagicMock,
        mock_update_status: MagicMock,
        mock_upload_chunk: MagicMock,
    ):
        """All events are flushed to S3 as JSONL chunks."""
        mock_engine, _mock_conn = _make_mock_engine()
        mock_create_engine.return_value = mock_engine

        run_id = uuid4()

        events = [
            {"seq": 1, "type": "setup", "ts": "t1", "content": "Starting"},
            {"seq": 2, "type": "case_start", "ts": "t2", "case_index": 0, "case_name": "c", "total_cases": 1},
            {
                "seq": 3,
                "type": "report",
                "ts": "t3",
                "passed": 1,
                "total": 1,
                "status": "completed",
                "total_duration_ms": 1000,
                "case_results": [
                    {
                        "name": "c",
                        "description": "d",
                        "verdict": "pass",
                        "reasoning": "ok",
                        "agent_output": "out",
                        "agent_stderr": "",
                        "exit_code": 0,
                        "duration_ms": 1000,
                        "stage": "judge",
                    }
                ],
            },
        ]
        mock_pipeline.return_value = iter(events)

        run_streaming_eval(
            run_id=run_id,
            version_id=uuid4(),
            skill_zip=b"fake-zip",
            eval_config=_make_config(),
            eval_cases=_make_cases(1),
            agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
            org_slug="test-org",
            skill_name="test-skill",
            judge_api_key="judge-key",
            database_url="postgresql://test",
            s3_client=MagicMock(),
            s3_bucket="test-bucket",
            log_s3_prefix=f"eval-logs/{run_id}/",
        )

        # Verify S3 chunk contains all events as JSONL
        assert mock_upload_chunk.call_count >= 1
        # Reconstruct all uploaded events from positional args
        uploaded_events = []
        for upload_call in mock_upload_chunk.call_args_list:
            # upload_eval_log_chunk(s3_client, s3_bucket, prefix, seq, events_jsonl)
            args = upload_call[0]
            jsonl_content = args[4]
            for line in jsonl_content.strip().split("\n"):
                if line:
                    uploaded_events.append(json.loads(line))
        assert len(uploaded_events) == 3

    @patch(_P_UPLOAD_CHUNK)
    @patch(_P_UPDATE_STATUS)
    @patch(_P_INSERT_REPORT)
    @patch(_P_CREATE_ENGINE)
    @patch(_P_PIPELINE)
    def test_exception_mid_pipeline_flushes_remaining_events(
        self,
        mock_pipeline: MagicMock,
        mock_create_engine: MagicMock,
        mock_insert_report: MagicMock,
        mock_update_status: MagicMock,
        mock_upload_chunk: MagicMock,
    ):
        """If pipeline raises mid-stream, buffered events are still flushed to S3."""
        mock_engine, _mock_conn = _make_mock_engine()
        mock_create_engine.return_value = mock_engine

        run_id = uuid4()

        def failing_pipeline(*args, **kwargs):
            yield {"seq": 1, "type": "setup", "ts": "t1", "content": "Starting"}
            yield {"seq": 2, "type": "case_start", "ts": "t2", "case_index": 0, "case_name": "c", "total_cases": 1}
            raise RuntimeError("Unexpected sandbox OOM")

        mock_pipeline.return_value = failing_pipeline()

        with pytest.raises(RuntimeError, match="Unexpected sandbox OOM"):
            run_streaming_eval(
                run_id=run_id,
                version_id=uuid4(),
                skill_zip=b"fake-zip",
                eval_config=_make_config(),
                eval_cases=_make_cases(1),
                agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
                org_slug="test-org",
                skill_name="test-skill",
                judge_api_key="judge-key",
                database_url="postgresql://test",
                s3_client=MagicMock(),
                s3_bucket="test-bucket",
                log_s3_prefix=f"eval-logs/{run_id}/",
            )

        # Buffered events should still be flushed to S3
        assert mock_upload_chunk.call_count >= 1

        # Run should be marked as failed
        failed_calls = [c for c in mock_update_status.call_args_list if c.kwargs.get("status") == "failed"]
        assert len(failed_calls) >= 1
