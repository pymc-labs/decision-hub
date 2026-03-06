"""Tests for domain/evals.py -- dynamic eval orchestration pipeline."""

from unittest.mock import MagicMock, patch

import pytest

from decision_hub.domain.evals import _redact_secrets, run_eval_pipeline
from decision_hub.models import EvalCase, EvalConfig


def _make_eval_config() -> EvalConfig:
    return EvalConfig(agent="claude", judge_model="claude-sonnet-4-5-20250929")


def _make_eval_cases() -> tuple[EvalCase, ...]:
    return (
        EvalCase(
            name="test-case-1",
            description="First test case",
            prompt="Run this analysis",
            judge_criteria="PASS: Agent produces output\nFAIL: Agent crashes",
        ),
        EvalCase(
            name="test-case-2",
            description="Second test case",
            prompt="Check data quality",
            judge_criteria="PASS: Agent checks for nulls\nFAIL: Agent ignores nulls",
        ),
    )


class TestRunEvalPipeline:
    @patch("decision_hub.domain.evals.judge_eval_output")
    @patch("decision_hub.domain.evals.run_eval_case_in_sandbox")
    @patch("decision_hub.domain.evals.get_agent_config")
    def test_all_cases_pass(
        self,
        mock_get_config: MagicMock,
        mock_sandbox: MagicMock,
        mock_judge: MagicMock,
    ) -> None:
        """Both cases pass: sandbox succeeds, judge says pass."""
        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")
        mock_sandbox.return_value = ("output text", "", 0, 5000)
        mock_judge.return_value = {"verdict": "pass", "reasoning": "Looks good"}

        case_results, passed, total, duration_ms = run_eval_pipeline(
            skill_zip=b"fake-zip",
            eval_config=_make_eval_config(),
            eval_cases=_make_eval_cases(),
            agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
            org_slug="test-org",
            skill_name="test-skill",
            runtime=None,
        )

        assert total == 2
        assert passed == 2
        assert len(case_results) == 2
        assert all(r["verdict"] == "pass" for r in case_results)
        assert all(r["stage"] == "judge" for r in case_results)
        assert duration_ms >= 0

    @patch("decision_hub.domain.evals.judge_eval_output")
    @patch("decision_hub.domain.evals.run_eval_case_in_sandbox")
    @patch("decision_hub.domain.evals.get_agent_config")
    def test_one_pass_one_fail(
        self,
        mock_get_config: MagicMock,
        mock_sandbox: MagicMock,
        mock_judge: MagicMock,
    ) -> None:
        """First case passes, second case fails judge."""
        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")
        mock_sandbox.return_value = ("output text", "", 0, 5000)
        mock_judge.side_effect = [
            {"verdict": "pass", "reasoning": "Good"},
            {"verdict": "fail", "reasoning": "Missing null check"},
        ]

        case_results, passed, total, _duration = run_eval_pipeline(
            skill_zip=b"fake-zip",
            eval_config=_make_eval_config(),
            eval_cases=_make_eval_cases(),
            agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
            org_slug="test-org",
            skill_name="test-skill",
            runtime=None,
        )

        assert total == 2
        assert passed == 1
        assert case_results[0]["verdict"] == "pass"
        assert case_results[1]["verdict"] == "fail"

    @patch("decision_hub.domain.evals.judge_eval_output")
    @patch("decision_hub.domain.evals.run_eval_case_in_sandbox")
    @patch("decision_hub.domain.evals.get_agent_config")
    def test_sandbox_failure_records_error(
        self,
        mock_get_config: MagicMock,
        mock_sandbox: MagicMock,
        mock_judge: MagicMock,
    ) -> None:
        """Sandbox crash -> verdict=error, stage=sandbox."""
        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")
        mock_sandbox.side_effect = RuntimeError("Container crashed")

        case_results, passed, total, _duration = run_eval_pipeline(
            skill_zip=b"fake-zip",
            eval_config=_make_eval_config(),
            eval_cases=(_make_eval_cases()[0],),
            agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
            org_slug="test-org",
            skill_name="test-skill",
            runtime=None,
        )

        assert total == 1
        assert passed == 0
        assert case_results[0]["verdict"] == "error"
        assert case_results[0]["stage"] == "sandbox"
        assert "Container crashed" in case_results[0]["reasoning"]
        mock_judge.assert_not_called()

    @patch("decision_hub.domain.evals.judge_eval_output")
    @patch("decision_hub.domain.evals.run_eval_case_in_sandbox")
    @patch("decision_hub.domain.evals.get_agent_config")
    def test_agent_nonzero_exit_records_error(
        self,
        mock_get_config: MagicMock,
        mock_sandbox: MagicMock,
        mock_judge: MagicMock,
    ) -> None:
        """Agent exits with non-zero -> verdict=error, stage=agent."""
        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")
        mock_sandbox.return_value = ("", "ModuleNotFoundError", 1, 3000)

        case_results, passed, total, _duration = run_eval_pipeline(
            skill_zip=b"fake-zip",
            eval_config=_make_eval_config(),
            eval_cases=(_make_eval_cases()[0],),
            agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
            org_slug="test-org",
            skill_name="test-skill",
            runtime=None,
        )

        assert total == 1
        assert passed == 0
        assert case_results[0]["verdict"] == "error"
        assert case_results[0]["stage"] == "agent"
        assert case_results[0]["exit_code"] == 1
        assert case_results[0]["agent_stderr"] == "ModuleNotFoundError"
        mock_judge.assert_not_called()

    @patch("decision_hub.domain.evals.judge_eval_output")
    @patch("decision_hub.domain.evals.run_eval_case_in_sandbox")
    @patch("decision_hub.domain.evals.get_agent_config")
    def test_judge_failure_records_error(
        self,
        mock_get_config: MagicMock,
        mock_sandbox: MagicMock,
        mock_judge: MagicMock,
    ) -> None:
        """Judge API fails -> verdict=error, stage=judge."""
        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")
        mock_sandbox.return_value = ("output", "", 0, 5000)
        mock_judge.side_effect = RuntimeError("API timeout")

        case_results, passed, total, _duration = run_eval_pipeline(
            skill_zip=b"fake-zip",
            eval_config=_make_eval_config(),
            eval_cases=(_make_eval_cases()[0],),
            agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
            org_slug="test-org",
            skill_name="test-skill",
            runtime=None,
        )

        assert total == 1
        assert passed == 0
        assert case_results[0]["verdict"] == "error"
        assert case_results[0]["stage"] == "judge"
        assert "API timeout" in case_results[0]["reasoning"]
        assert case_results[0]["agent_output"] == "output"

    @patch("decision_hub.domain.evals.judge_eval_output")
    @patch("decision_hub.domain.evals.run_eval_case_in_sandbox")
    @patch("decision_hub.domain.evals.get_agent_config")
    def test_duration_tracked_per_case(
        self,
        mock_get_config: MagicMock,
        mock_sandbox: MagicMock,
        mock_judge: MagicMock,
    ) -> None:
        """Each case records its own duration_ms from sandbox."""
        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")
        mock_sandbox.side_effect = [
            ("out1", "", 0, 10000),
            ("out2", "", 0, 20000),
        ]
        mock_judge.return_value = {"verdict": "pass", "reasoning": "ok"}

        case_results, _, _, _ = run_eval_pipeline(
            skill_zip=b"fake-zip",
            eval_config=_make_eval_config(),
            eval_cases=_make_eval_cases(),
            agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
            org_slug="test-org",
            skill_name="test-skill",
            runtime=None,
        )

        assert case_results[0]["duration_ms"] == 10000
        assert case_results[1]["duration_ms"] == 20000


class TestRedactSecrets:
    """Tests for _redact_secrets — security-critical secret filtering."""

    def test_anthropic_key_redacted(self) -> None:
        """Anthropic API keys (sk-ant-...) are redacted."""
        text = "Using key sk-ant-api03-abcdefghijklmnopqrstu"
        assert _redact_secrets(text) == "Using key [REDACTED]"

    def test_openai_key_redacted(self) -> None:
        """OpenAI API keys (sk-...) are redacted."""
        text = "export OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwx"
        assert _redact_secrets(text) == "export OPENAI_API_KEY=[REDACTED]"

    def test_google_api_key_redacted(self) -> None:
        """Google API keys (AIza...) are redacted."""
        text = "key=AIzaSyB1234567890abcdefghijklmnopqrstuv"
        assert _redact_secrets(text) == "key=[REDACTED]"

    def test_no_secrets_unchanged(self) -> None:
        """Text without secrets passes through unchanged."""
        text = "This is normal output with no API keys."
        assert _redact_secrets(text) == text

    def test_multiple_secrets_all_redacted(self) -> None:
        """Multiple secrets in the same string are all redacted."""
        text = (
            "anthropic=sk-ant-api03-AAAAAAAAAAAAAAAAAAAAAA "
            "openai=sk-BBBBBBBBBBBBBBBBBBBBBBBBBB "
            "google=AIzaSyC1234567890abcdefghijklmnopqrstuv"
        )
        result = _redact_secrets(text)
        assert "sk-ant" not in result
        assert "sk-B" not in result
        assert "AIza" not in result
        assert result.count("[REDACTED]") == 3

    def test_short_sk_prefix_not_redacted(self) -> None:
        """Short strings starting with sk- that are under 20 chars are NOT redacted."""
        text = "sk-short"
        assert _redact_secrets(text) == "sk-short"

    @pytest.mark.parametrize(
        "key",
        [
            "sk-ant-api03-" + "a" * 40,
            "sk-" + "A" * 48,
            "sk-proj-" + "x" * 30,
            "AIzaSy" + "B" * 35,
        ],
        ids=["anthropic-long", "openai-long", "openai-proj", "google-long"],
    )
    def test_various_key_lengths(self, key: str) -> None:
        """Keys of various realistic lengths are redacted."""
        assert _redact_secrets(f"key={key}") == "key=[REDACTED]"

    def test_key_embedded_in_json(self) -> None:
        """Keys inside JSON strings are redacted."""
        text = '{"api_key": "sk-ant-api03-TestKeyValue1234567890abcdef"}'
        result = _redact_secrets(text)
        assert "sk-ant" not in result
        assert "[REDACTED]" in result


class TestInsertEvalReportConflict:
    """Verify that insert_eval_report raises IntegrityError on duplicate version_id.

    The eval_reports table has a UNIQUE constraint on version_id. When
    insert_eval_report is called twice for the same version_id (e.g. due
    to a retry or race condition), the second call should raise
    IntegrityError from the database constraint, not silently overwrite.
    """

    @patch("decision_hub.domain.evals.run_eval_case_in_sandbox")
    @patch("decision_hub.domain.evals.judge_eval_output")
    @patch("decision_hub.domain.evals.get_agent_config")
    def test_duplicate_eval_report_raises_integrity_error(
        self,
        mock_get_config: MagicMock,
        mock_judge: MagicMock,
        mock_sandbox: MagicMock,
    ) -> None:
        """Two pipeline runs for the same version_id: second insert should propagate IntegrityError.

        Since insert_eval_report does a plain INSERT (no ON CONFLICT),
        the unique constraint on version_id will cause IntegrityError.
        The caller (registry_service) wraps this in a try/except.
        """
        from sqlalchemy.exc import IntegrityError

        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")
        mock_sandbox.return_value = ("output", "", 0, 5000)
        mock_judge.return_value = {"verdict": "pass", "reasoning": "ok"}

        # Run the pipeline twice -- both produce results
        for _ in range(2):
            _case_results, passed, total, _ = run_eval_pipeline(
                skill_zip=b"fake-zip",
                eval_config=_make_eval_config(),
                eval_cases=(_make_eval_cases()[0],),
                agent_env_vars={"ANTHROPIC_API_KEY": "test-key"},
                org_slug="test-org",
                skill_name="test-skill",
                runtime=None,
            )
            assert passed == 1
            assert total == 1

        # Now simulate the DB layer: the second insert_eval_report call
        # for the same version_id would raise IntegrityError
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = IntegrityError(
            "duplicate key value violates unique constraint",
            params=None,
            orig=Exception(),
        )

        from decision_hub.infra.database import insert_eval_report

        with pytest.raises(IntegrityError):
            insert_eval_report(
                mock_conn,
                version_id=MagicMock(),
                agent="claude",
                judge_model="claude-sonnet-4-5-20250929",
                case_results=[{"verdict": "pass"}],
                passed=1,
                total=1,
                total_duration_ms=5000,
                status="completed",
            )
