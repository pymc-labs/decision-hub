"""Tests for the streaming assessment pipeline in domain/evals.py."""

from unittest.mock import MagicMock, patch

from decision_hub.domain.evals import (
    _make_event,
    _redact_secrets,
    _truncate,
    stream_eval_pipeline,
)
from decision_hub.models import EvalCase, EvalConfig


def _make_config() -> EvalConfig:
    return EvalConfig(agent="claude", judge_model="claude-sonnet-4-5-20250929")


def _make_cases() -> tuple[EvalCase, ...]:
    return (
        EvalCase(
            name="basic-analysis",
            description="Run basic analysis",
            prompt="Analyze this data",
            judge_criteria="PASS: produces output\nFAIL: crashes",
        ),
    )


class TestRedactSecrets:
    def test_anthropic_key_redacted(self):
        text = "Key is sk-ant-api03-abc123def456ghi789jklmno"
        assert "[REDACTED]" in _redact_secrets(text)
        assert "sk-ant" not in _redact_secrets(text)

    def test_openai_key_redacted(self):
        text = "Using key sk-1234567890abcdefghijklmnop"
        assert "[REDACTED]" in _redact_secrets(text)

    def test_google_key_redacted(self):
        text = "Key AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
        assert "[REDACTED]" in _redact_secrets(text)

    def test_no_secrets_unchanged(self):
        text = "Hello world, no secrets here"
        assert _redact_secrets(text) == text


class TestTruncate:
    def test_short_text_unchanged(self):
        assert _truncate("hello", 100) == "hello"

    def test_long_text_truncated(self):
        result = _truncate("a" * 200, 100)
        assert len(result) < 200
        assert result.endswith("...[truncated]")


class TestMakeEvent:
    def test_basic_event(self):
        event = _make_event(1, "setup", content="Building sandbox...")
        assert event["seq"] == 1
        assert event["type"] == "setup"
        assert event["content"] == "Building sandbox..."
        assert "ts" in event

    def test_event_redacts_secrets(self):
        event = _make_event(1, "log", content="Key is sk-ant-api03-abc123def456ghi789jklmno")
        assert "sk-ant" not in event["content"]
        assert "[REDACTED]" in event["content"]


class TestStreamEvalPipeline:
    @patch("decision_hub.domain.evals.judge_eval_output")
    @patch("decision_hub.domain.evals.stream_eval_case_in_sandbox")
    @patch("decision_hub.domain.evals.get_agent_config")
    def test_yields_correct_event_sequence(
        self,
        mock_get_config: MagicMock,
        mock_stream_sandbox: MagicMock,
        mock_judge: MagicMock,
    ):
        """Single passing case yields: setup, case_start, log(s), judge_start, case_result, report."""
        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")

        # stream_eval_case_in_sandbox is a generator that yields output events
        # and returns final results via StopIteration.value
        def fake_stream(*args, **kwargs):
            yield {"stream": "stdout", "content": "analysis output"}
            return ("analysis output", "", 0, 5000)

        mock_stream_sandbox.side_effect = fake_stream
        mock_judge.return_value = {"verdict": "pass", "reasoning": "Good output"}

        events = list(
            stream_eval_pipeline(
                skill_zip=b"fake-zip",
                eval_config=_make_config(),
                eval_cases=_make_cases(),
                agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
                org_slug="test-org",
                skill_name="test-skill",
            )
        )

        event_types = [e["type"] for e in events]
        assert event_types[0] == "setup"
        assert event_types[1] == "case_start"
        assert "log" in event_types
        assert "judge_start" in event_types
        assert "case_result" in event_types
        assert event_types[-1] == "report"

        # Verify seqs are monotonically increasing
        seqs = [e["seq"] for e in events]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)  # all unique

    @patch("decision_hub.domain.evals.judge_eval_output")
    @patch("decision_hub.domain.evals.stream_eval_case_in_sandbox")
    @patch("decision_hub.domain.evals.get_agent_config")
    def test_sandbox_error_yields_error_result(
        self,
        mock_get_config: MagicMock,
        mock_stream_sandbox: MagicMock,
        mock_judge: MagicMock,
    ):
        """Sandbox crash yields case_result with verdict=error."""
        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")
        mock_stream_sandbox.side_effect = RuntimeError("Container OOM")

        events = list(
            stream_eval_pipeline(
                skill_zip=b"fake-zip",
                eval_config=_make_config(),
                eval_cases=_make_cases(),
                agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
                org_slug="test-org",
                skill_name="test-skill",
            )
        )

        case_results = [e for e in events if e["type"] == "case_result"]
        assert len(case_results) == 1
        assert case_results[0]["verdict"] == "error"
        assert "Container OOM" in case_results[0]["reasoning"]
        mock_judge.assert_not_called()

    @patch("decision_hub.domain.evals.judge_eval_output")
    @patch("decision_hub.domain.evals.stream_eval_case_in_sandbox")
    @patch("decision_hub.domain.evals.get_agent_config")
    def test_report_event_contains_summary(
        self,
        mock_get_config: MagicMock,
        mock_stream_sandbox: MagicMock,
        mock_judge: MagicMock,
    ):
        """Final report event contains passed, total, status."""
        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")

        def fake_stream(*args, **kwargs):
            yield {"stream": "stdout", "content": "output"}
            return ("output", "", 0, 5000)

        mock_stream_sandbox.side_effect = fake_stream
        mock_judge.return_value = {"verdict": "pass", "reasoning": "ok"}

        events = list(
            stream_eval_pipeline(
                skill_zip=b"fake-zip",
                eval_config=_make_config(),
                eval_cases=_make_cases(),
                agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
                org_slug="test-org",
                skill_name="test-skill",
            )
        )

        report = next(e for e in events if e["type"] == "report")
        assert report["passed"] == 1
        assert report["total"] == 1
        assert report["status"] == "completed"
        assert report["total_duration_ms"] == 5000

    @patch("decision_hub.domain.evals.judge_eval_output")
    @patch("decision_hub.domain.evals.stream_eval_case_in_sandbox")
    @patch("decision_hub.domain.evals.get_agent_config")
    def test_multiple_cases_one_pass_one_fail(
        self,
        mock_get_config: MagicMock,
        mock_stream_sandbox: MagicMock,
        mock_judge: MagicMock,
    ):
        """Two cases: first passes, second fails judge — report status is 'failed'."""
        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")

        call_count = 0

        def fake_stream(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            yield {"stream": "stdout", "content": f"output-{call_count}"}
            return (f"output-{call_count}", "", 0, 3000)

        mock_stream_sandbox.side_effect = fake_stream
        mock_judge.side_effect = [
            {"verdict": "pass", "reasoning": "Good"},
            {"verdict": "fail", "reasoning": "Missing null check"},
        ]

        two_cases = (
            EvalCase(
                name="case-a",
                description="First case",
                prompt="Do A",
                judge_criteria="PASS: does A",
            ),
            EvalCase(
                name="case-b",
                description="Second case",
                prompt="Do B",
                judge_criteria="PASS: does B",
            ),
        )

        events = list(
            stream_eval_pipeline(
                skill_zip=b"fake-zip",
                eval_config=_make_config(),
                eval_cases=two_cases,
                agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
                org_slug="test-org",
                skill_name="test-skill",
            )
        )

        case_results = [e for e in events if e["type"] == "case_result"]
        assert len(case_results) == 2
        assert case_results[0]["verdict"] == "pass"
        assert case_results[1]["verdict"] == "fail"

        report = next(e for e in events if e["type"] == "report")
        assert report["passed"] == 1
        assert report["total"] == 2
        assert report["status"] == "failed"

        # Verify both case_start events are present with correct indices
        case_starts = [e for e in events if e["type"] == "case_start"]
        assert len(case_starts) == 2
        assert case_starts[0]["case_index"] == 0
        assert case_starts[1]["case_index"] == 1

    @patch("decision_hub.domain.evals.judge_eval_output")
    @patch("decision_hub.domain.evals.stream_eval_case_in_sandbox")
    @patch("decision_hub.domain.evals.get_agent_config")
    def test_nonzero_exit_yields_error_without_judging(
        self,
        mock_get_config: MagicMock,
        mock_stream_sandbox: MagicMock,
        mock_judge: MagicMock,
    ):
        """Agent non-zero exit yields case_result with verdict=error, stage=agent, skips judge."""
        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")

        def fake_stream(*args, **kwargs):
            yield {"stream": "stderr", "content": "ModuleNotFoundError: no module named 'pandas'"}
            return ("", "ModuleNotFoundError: no module named 'pandas'", 1, 4000)

        mock_stream_sandbox.side_effect = fake_stream

        events = list(
            stream_eval_pipeline(
                skill_zip=b"fake-zip",
                eval_config=_make_config(),
                eval_cases=_make_cases(),
                agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
                org_slug="test-org",
                skill_name="test-skill",
            )
        )

        case_results = [e for e in events if e["type"] == "case_result"]
        assert len(case_results) == 1
        assert case_results[0]["verdict"] == "error"
        assert "exit" in case_results[0]["reasoning"].lower()

        # Judge should never be called for non-zero exit
        mock_judge.assert_not_called()

        # No judge_start event should be emitted
        judge_starts = [e for e in events if e["type"] == "judge_start"]
        assert len(judge_starts) == 0

        # Report should reflect the error
        report = next(e for e in events if e["type"] == "report")
        assert report["status"] == "failed"
        assert report["passed"] == 0

    @patch("decision_hub.domain.evals.judge_eval_output")
    @patch("decision_hub.domain.evals.stream_eval_case_in_sandbox")
    @patch("decision_hub.domain.evals.get_agent_config")
    def test_judge_failure_yields_error_result(
        self,
        mock_get_config: MagicMock,
        mock_stream_sandbox: MagicMock,
        mock_judge: MagicMock,
    ):
        """Judge API exception yields case_result with verdict=error, stage=judge."""
        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")

        def fake_stream(*args, **kwargs):
            yield {"stream": "stdout", "content": "good output"}
            return ("good output", "", 0, 5000)

        mock_stream_sandbox.side_effect = fake_stream
        mock_judge.side_effect = RuntimeError("Anthropic API rate limited")

        events = list(
            stream_eval_pipeline(
                skill_zip=b"fake-zip",
                eval_config=_make_config(),
                eval_cases=_make_cases(),
                agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
                org_slug="test-org",
                skill_name="test-skill",
            )
        )

        # judge_start should be emitted before judge failure
        judge_starts = [e for e in events if e["type"] == "judge_start"]
        assert len(judge_starts) == 1

        case_results = [e for e in events if e["type"] == "case_result"]
        assert len(case_results) == 1
        assert case_results[0]["verdict"] == "error"
        assert "rate limited" in case_results[0]["reasoning"].lower()

        report = next(e for e in events if e["type"] == "report")
        assert report["status"] == "failed"
        assert report["passed"] == 0
