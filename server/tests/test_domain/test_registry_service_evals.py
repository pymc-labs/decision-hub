"""Tests for eval-related functions in registry_service.py.

Covers the publish-flow eval triggering logic:
- maybe_trigger_agent_assessment(): decides whether to trigger evals
- Validation of config/cases combinations

Note: maybe_trigger_agent_assessment uses lazy imports (modal, database),
so patches target the source modules.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from decision_hub.domain.publish_pipeline import maybe_trigger_agent_assessment
from decision_hub.models import EvalCase, EvalConfig


def _make_eval_config() -> EvalConfig:
    return EvalConfig(agent="claude", judge_model="claude-sonnet-4-5-20250929")


def _make_eval_cases(n: int = 2) -> tuple[EvalCase, ...]:
    return tuple(
        EvalCase(
            name=f"case-{i}",
            description=f"Test case {i}",
            prompt=f"Run test {i}",
            judge_criteria="PASS: produces output\nFAIL: crashes",
        )
        for i in range(n)
    )


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.database_url = "postgresql://test"
    settings.modal_app_name = "decision-hub-dev"
    settings.s3_bucket = "test-bucket"
    return settings


class TestMaybeTriggerAgentAssessment:
    """Tests for the eval trigger decision logic."""

    def test_no_eval_config_returns_none(self):
        """When eval_config is None, no eval is triggered."""
        status, run_id = maybe_trigger_agent_assessment(
            eval_config=None,
            eval_cases=(),
            s3_key="skills/test.zip",
            s3_bucket="test-bucket",
            version_id=uuid4(),
            org_slug="test-org",
            skill_name="test-skill",
            settings=_make_settings(),
            user_id=uuid4(),
        )

        assert status is None
        assert run_id is None

    def test_no_eval_config_with_cases_returns_none(self):
        """When eval_config is None but cases exist, no eval is triggered."""
        status, run_id = maybe_trigger_agent_assessment(
            eval_config=None,
            eval_cases=_make_eval_cases(1),
            s3_key="skills/test.zip",
            s3_bucket="test-bucket",
            version_id=uuid4(),
            org_slug="test-org",
            skill_name="test-skill",
            settings=_make_settings(),
            user_id=uuid4(),
        )

        assert status is None
        assert run_id is None

    def test_config_without_cases_raises_value_error(self):
        """Config declared but no case files raises ValueError."""
        with pytest.raises(ValueError, match="no case files"):
            maybe_trigger_agent_assessment(
                eval_config=_make_eval_config(),
                eval_cases=(),  # No cases
                s3_key="skills/test.zip",
                s3_bucket="test-bucket",
                version_id=uuid4(),
                org_slug="test-org",
                skill_name="test-skill",
                settings=_make_settings(),
                user_id=uuid4(),
            )

    @patch("modal.Function")
    @patch("decision_hub.infra.database.insert_eval_run")
    @patch("decision_hub.infra.database.create_engine")
    def test_config_with_cases_creates_run_and_spawns(
        self,
        mock_create_engine: MagicMock,
        mock_insert_run: MagicMock,
        mock_modal_function: MagicMock,
    ):
        """Config + cases creates eval_run row, spawns Modal function, returns pending."""
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        mock_run = MagicMock()
        mock_run.id = uuid4()
        mock_insert_run.return_value = mock_run

        mock_fn = MagicMock()
        mock_modal_function.from_name.return_value = mock_fn

        version_id = uuid4()
        user_id = uuid4()
        settings = _make_settings()

        status, run_id = maybe_trigger_agent_assessment(
            eval_config=_make_eval_config(),
            eval_cases=_make_eval_cases(2),
            s3_key="skills/test-org/test-skill/1.0.0.zip",
            s3_bucket="test-bucket",
            version_id=version_id,
            org_slug="test-org",
            skill_name="test-skill",
            settings=settings,
            user_id=user_id,
        )

        assert status == "pending"
        assert run_id == str(mock_run.id)

        # Verify eval_run was inserted with correct params
        mock_insert_run.assert_called_once()
        insert_kwargs = mock_insert_run.call_args.kwargs
        assert insert_kwargs["version_id"] == version_id
        assert insert_kwargs["user_id"] == user_id
        assert insert_kwargs["agent"] == "claude"
        assert insert_kwargs["total_cases"] == 2
        assert insert_kwargs["log_s3_prefix"].startswith("eval-logs/")

        # Verify Modal function was spawned
        mock_modal_function.from_name.assert_called_once_with(
            settings.modal_app_name,
            "run_eval_task",
        )
        mock_fn.spawn.assert_called_once()
        spawn_kwargs = mock_fn.spawn.call_args.kwargs
        assert spawn_kwargs["version_id"] == str(version_id)
        assert spawn_kwargs["eval_agent"] == "claude"
        assert spawn_kwargs["org_slug"] == "test-org"
        assert spawn_kwargs["skill_name"] == "test-skill"
        assert spawn_kwargs["user_id"] == str(user_id)
        assert len(spawn_kwargs["eval_cases_dicts"]) == 2

    @patch("modal.Function")
    @patch("decision_hub.infra.database.insert_eval_run")
    @patch("decision_hub.infra.database.create_engine")
    def test_eval_cases_serialized_as_dicts(
        self,
        mock_create_engine: MagicMock,
        mock_insert_run: MagicMock,
        mock_modal_function: MagicMock,
    ):
        """EvalCase dataclasses are correctly serialized to dicts for Modal transport."""
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn
        mock_create_engine.return_value = mock_engine

        mock_run = MagicMock()
        mock_run.id = uuid4()
        mock_insert_run.return_value = mock_run

        mock_fn = MagicMock()
        mock_modal_function.from_name.return_value = mock_fn

        cases = (
            EvalCase(
                name="my-case",
                description="Desc",
                prompt="Do something",
                judge_criteria="PASS: works\nFAIL: breaks",
            ),
        )

        maybe_trigger_agent_assessment(
            eval_config=_make_eval_config(),
            eval_cases=cases,
            s3_key="skills/test.zip",
            s3_bucket="test-bucket",
            version_id=uuid4(),
            org_slug="test-org",
            skill_name="test-skill",
            settings=_make_settings(),
            user_id=uuid4(),
        )

        spawn_kwargs = mock_fn.spawn.call_args.kwargs
        case_dicts = spawn_kwargs["eval_cases_dicts"]
        assert len(case_dicts) == 1
        assert case_dicts[0] == {
            "name": "my-case",
            "description": "Desc",
            "prompt": "Do something",
            "judge_criteria": "PASS: works\nFAIL: breaks",
        }
