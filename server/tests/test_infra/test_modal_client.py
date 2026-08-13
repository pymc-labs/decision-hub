"""Tests for decision_hub.infra.modal_client -- API key validation and zip safety."""

import io
import sys
import zipfile
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from decision_hub.infra.modal_client import _extract_skill_body, validate_api_key


def _make_skill_body(marker: str) -> str:
    """Minimal SKILL.md frontmatter+body with a distinguishable body marker."""
    return f"---\nname: test-skill\ndescription: test\n---\n{marker}\n"


class TestValidateApiKey:
    @respx.mock
    def test_raises_on_401(self):
        respx.get("https://api.anthropic.com/v1/models").mock(return_value=httpx.Response(401))
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is invalid"):
            validate_api_key("ANTHROPIC_API_KEY", "sk-bad-key")

    @respx.mock
    def test_passes_on_200(self):
        respx.get("https://api.anthropic.com/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))
        validate_api_key("ANTHROPIC_API_KEY", "sk-good-key")

    def test_skips_unknown_provider(self):
        # Should not raise for providers without a validation endpoint
        validate_api_key("SOME_OTHER_KEY", "any-value")

    @respx.mock
    def test_does_not_block_on_network_error(self):
        respx.get("https://api.anthropic.com/v1/models").mock(side_effect=httpx.ConnectError("connection refused"))
        # Should not raise — network issues are transient
        validate_api_key("ANTHROPIC_API_KEY", "sk-any-key")


class TestSandboxZipSlipProtection:
    """_create_skill_sandbox rejects zip archives with path-traversal entries."""

    @staticmethod
    def _make_zip(entries: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, data in entries.items():
                zf.writestr(name, data)
        return buf.getvalue()

    def test_rejects_traversal_entry(self) -> None:
        """A zip with ../../.bashrc should raise ValueError before writing."""
        from decision_hub.infra.modal_client import _create_skill_sandbox
        from decision_hub.models import AgentSandboxConfig

        config = AgentSandboxConfig(
            npm_package="test-agent",
            skills_path=".test/skills",
            run_cmd=("test",),
            key_env_var="TEST_KEY",
            extra_env={},
        )

        # Set up minimal mock sandbox
        mock_modal = MagicMock()
        mock_sb = MagicMock()
        mock_modal.App.lookup.return_value = MagicMock()
        mock_modal.Sandbox.create.return_value = mock_sb
        mock_modal.Secret.from_dict.return_value = MagicMock()

        malicious_zip = self._make_zip({"../../.bashrc": b"malicious"})

        with (
            patch.dict(sys.modules, {"modal": mock_modal}),
            pytest.raises(ValueError, match="escapes target directory"),
        ):
            _create_skill_sandbox(
                malicious_zip,
                config,
                {"TEST_KEY": "fake-key"},
                "testorg",
                "testskill",
            )

    def test_accepts_safe_zip(self) -> None:
        """A zip with normal entries should not raise."""
        from decision_hub.infra.modal_client import _create_skill_sandbox
        from decision_hub.models import AgentSandboxConfig

        config = AgentSandboxConfig(
            npm_package="test-agent",
            skills_path=".test/skills",
            run_cmd=("test",),
            key_env_var="TEST_KEY",
            extra_env={},
        )

        mock_modal = MagicMock()
        mock_sb = MagicMock()
        mock_modal.App.lookup.return_value = MagicMock()
        mock_modal.Sandbox.create.return_value = mock_sb
        mock_modal.Secret.from_dict.return_value = MagicMock()

        # Mock _run_in_sandbox to return plausible results
        mock_sb.exec.return_value = MagicMock(
            stdout=MagicMock(read=MagicMock(return_value="")),
            returncode=0,
            wait=MagicMock(),
        )

        safe_zip = self._make_zip(
            {
                "SKILL.md": b"---\nname: test\n---\nbody\n",
                "scripts/run.py": b"print('ok')",
            }
        )

        with patch.dict(sys.modules, {"modal": mock_modal}):
            sb, skill_path = _create_skill_sandbox(
                safe_zip,
                config,
                {"TEST_KEY": "fake-key"},
                "testorg",
                "testskill",
            )
        assert sb is mock_sb
        assert "testorg/testskill" in skill_path


class TestExtractSkillBody:
    """_extract_skill_body must select the real SKILL.md, not lookalikes.

    Regression: the previous ``name.endswith("SKILL.md")`` also matched
    entries like MYSKILL.md and any deeper path segment, and the winner
    depended on ``namelist()`` order. That silently diverged from the
    gauntlet's basename-equality check, so the agent could run with a
    different system prompt than the one the safety scan reviewed.
    """

    @staticmethod
    def _zip(entries: dict[str, bytes]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, data in entries.items():
                zf.writestr(name, data)
        return buf.getvalue()

    def test_prefers_true_skill_md_over_lookalike(self) -> None:
        # Put the decoy FIRST so a naive endswith() picks it.
        zip_bytes = self._zip(
            {
                "MYSKILL.md": _make_skill_body("DECOY body").encode(),
                "SKILL.md": _make_skill_body("REAL body").encode(),
            }
        )
        assert _extract_skill_body(zip_bytes) == "REAL body"

    def test_matches_nested_skill_md(self) -> None:
        zip_bytes = self._zip({"pkg/SKILL.md": _make_skill_body("NESTED body").encode()})
        assert _extract_skill_body(zip_bytes) == "NESTED body"

    def test_ignores_backup_extensions(self) -> None:
        zip_bytes = self._zip({"SKILL.md.bak": _make_skill_body("BAK body").encode()})
        assert _extract_skill_body(zip_bytes) == ""
