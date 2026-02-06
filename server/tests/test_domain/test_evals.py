"""Tests for domain/evals.py -- dynamic eval orchestration pipeline."""

from unittest.mock import MagicMock, patch

from decision_hub.domain.evals import run_eval_pipeline
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
