"""Tests for decision_hub.api.registry_service — judge key isolation."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

from cryptography.fernet import Fernet

from decision_hub.api.registry_service import run_assessment_background


def _make_settings(fernet_key: str) -> MagicMock:
    s = MagicMock()
    s.database_url = "postgresql://fake"
    s.fernet_key = fernet_key
    s.aws_region = "us-east-1"
    s.aws_access_key_id = "AKIA_FAKE"
    s.aws_secret_access_key = "fake_secret"
    s.s3_bucket = "test-bucket"
    s.sandbox_memory_mb = 4096
    s.sandbox_timeout_seconds = 900
    s.sandbox_cpu = 2.0
    return s


def _encrypt(fernet: Fernet, value: str) -> bytes:
    return fernet.encrypt(value.encode())


def _make_eval_case() -> MagicMock:
    case = MagicMock()
    case.name = "test"
    case.description = "test case"
    case.prompt = "do something"
    case.judge_criteria = "PASS: ok"
    return case


# All patches target the source modules because run_assessment_background
# imports them inside the function body with `from ... import ...`.
_DB_MOD = "decision_hub.infra.database"
_MODAL_MOD = "decision_hub.infra.modal_client"
_EVALS_MOD = "decision_hub.domain.evals"


class TestJudgeKeyIsolation:
    """Verify that the judge API key is stripped from sandbox env vars
    when it differs from the agent's runtime key."""

    @patch(f"{_EVALS_MOD}.run_eval_pipeline")
    @patch(f"{_MODAL_MOD}.validate_api_key")
    @patch(f"{_MODAL_MOD}.get_agent_config")
    @patch(f"{_DB_MOD}.get_api_keys_for_eval")
    @patch(f"{_DB_MOD}.create_engine")
    def test_codex_agent_excludes_judge_key_from_sandbox(
        self,
        mock_engine: MagicMock,
        mock_get_keys: MagicMock,
        mock_get_config: MagicMock,
        mock_validate: MagicMock,
        mock_run_pipeline: MagicMock,
    ) -> None:
        """For codex agent, ANTHROPIC_API_KEY (judge) must not appear in agent_env_vars."""
        real_key = Fernet.generate_key()
        fernet = Fernet(real_key)
        settings = _make_settings(real_key.decode())

        mock_get_config.return_value = MagicMock(key_env_var="CODEX_API_KEY")

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_keys.return_value = {
            "CODEX_API_KEY": _encrypt(fernet, "codex-key-value"),
            "ANTHROPIC_API_KEY": _encrypt(fernet, "judge-key-value"),
        }

        mock_run_pipeline.return_value = ([], 0, 0, 0)

        eval_config = MagicMock(agent="codex", judge_model="claude-sonnet-4-5-20250929")

        run_assessment_background(
            version_id=uuid4(),
            assessment_config=eval_config,
            assessment_cases=(_make_eval_case(),),
            skill_zip=b"fake-zip",
            org_slug="test-org",
            skill_name="test-skill",
            settings=settings,
            user_id=uuid4(),
            run_id=None,
        )

        mock_run_pipeline.assert_called_once()
        _, kwargs = mock_run_pipeline.call_args
        agent_env = kwargs["agent_env_vars"]

        # The judge key must NOT be in agent_env_vars (sandbox env)
        assert "ANTHROPIC_API_KEY" not in agent_env, (
            "Judge key ANTHROPIC_API_KEY must not be passed to the sandbox for codex agent"
        )
        assert agent_env["CODEX_API_KEY"] == "codex-key-value"

        # The judge key must be passed separately
        assert kwargs["judge_api_key"] == "judge-key-value"

    @patch(f"{_EVALS_MOD}.run_eval_pipeline")
    @patch(f"{_MODAL_MOD}.validate_api_key")
    @patch(f"{_MODAL_MOD}.get_agent_config")
    @patch(f"{_DB_MOD}.get_api_keys_for_eval")
    @patch(f"{_DB_MOD}.create_engine")
    def test_claude_agent_keeps_key_in_sandbox(
        self,
        mock_engine: MagicMock,
        mock_get_keys: MagicMock,
        mock_get_config: MagicMock,
        mock_validate: MagicMock,
        mock_run_pipeline: MagicMock,
    ) -> None:
        """For claude agent, ANTHROPIC_API_KEY must remain in agent_env_vars."""
        real_key = Fernet.generate_key()
        fernet = Fernet(real_key)
        settings = _make_settings(real_key.decode())

        mock_get_config.return_value = MagicMock(key_env_var="ANTHROPIC_API_KEY")

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_keys.return_value = {
            "ANTHROPIC_API_KEY": _encrypt(fernet, "shared-key-value"),
        }

        mock_run_pipeline.return_value = ([], 0, 0, 0)

        eval_config = MagicMock(agent="claude", judge_model="claude-sonnet-4-5-20250929")

        run_assessment_background(
            version_id=uuid4(),
            assessment_config=eval_config,
            assessment_cases=(_make_eval_case(),),
            skill_zip=b"fake-zip",
            org_slug="test-org",
            skill_name="test-skill",
            settings=settings,
            user_id=uuid4(),
            run_id=None,
        )

        mock_run_pipeline.assert_called_once()
        _, kwargs = mock_run_pipeline.call_args
        agent_env = kwargs["agent_env_vars"]

        # For Claude, the key must remain — it's the agent's own runtime key
        assert "ANTHROPIC_API_KEY" in agent_env, "ANTHROPIC_API_KEY must remain in sandbox env for Claude agent"
        assert agent_env["ANTHROPIC_API_KEY"] == "shared-key-value"

    @patch(f"{_EVALS_MOD}.run_eval_pipeline")
    @patch(f"{_MODAL_MOD}.validate_api_key")
    @patch(f"{_MODAL_MOD}.get_agent_config")
    @patch(f"{_DB_MOD}.get_api_keys_for_eval")
    @patch(f"{_DB_MOD}.create_engine")
    def test_gemini_agent_excludes_judge_key_from_sandbox(
        self,
        mock_engine: MagicMock,
        mock_get_keys: MagicMock,
        mock_get_config: MagicMock,
        mock_validate: MagicMock,
        mock_run_pipeline: MagicMock,
    ) -> None:
        """For gemini agent, ANTHROPIC_API_KEY (judge) must not appear in agent_env_vars."""
        real_key = Fernet.generate_key()
        fernet = Fernet(real_key)
        settings = _make_settings(real_key.decode())

        mock_get_config.return_value = MagicMock(key_env_var="GEMINI_API_KEY")

        mock_conn = MagicMock()
        mock_engine.return_value.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_get_keys.return_value = {
            "GEMINI_API_KEY": _encrypt(fernet, "gemini-key-value"),
            "ANTHROPIC_API_KEY": _encrypt(fernet, "judge-key-value"),
        }

        mock_run_pipeline.return_value = ([], 0, 0, 0)

        eval_config = MagicMock(agent="gemini", judge_model="claude-sonnet-4-5-20250929")

        run_assessment_background(
            version_id=uuid4(),
            assessment_config=eval_config,
            assessment_cases=(_make_eval_case(),),
            skill_zip=b"fake-zip",
            org_slug="test-org",
            skill_name="test-skill",
            settings=settings,
            user_id=uuid4(),
            run_id=None,
        )

        mock_run_pipeline.assert_called_once()
        _, kwargs = mock_run_pipeline.call_args
        agent_env = kwargs["agent_env_vars"]

        assert "ANTHROPIC_API_KEY" not in agent_env
        assert agent_env["GEMINI_API_KEY"] == "gemini-key-value"
        assert kwargs["judge_api_key"] == "judge-key-value"
