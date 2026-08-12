"""Tests for decision_hub.infra.modal_client -- API key validation, zip safety, and network egress."""

import io
import socket
import sys
import zipfile
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from decision_hub.infra.modal_client import (
    _INFRA_HOSTS,
    AGENT_CONFIGS,
    _resolve_egress_cidrs,
    validate_api_key,
)
from decision_hub.models import AgentSandboxConfig


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


class TestResolveEgressCidrs:
    """Tests for _resolve_egress_cidrs — DNS → /32 CIDR conversion."""

    def _fake_getaddrinfo(self, mapping: dict[str, list[str]]):
        """Return a patched getaddrinfo that returns IPs from *mapping*."""

        def _getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            ips = mapping.get(host)
            if ips is None:
                raise socket.gaierror(f"Name or service not known: {host}")
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

        return _getaddrinfo

    def test_resolves_api_and_infra_hosts(self):
        config = AgentSandboxConfig(
            npm_package="test-agent",
            skills_path=".test/skills",
            run_cmd=("test",),
            key_env_var="TEST_KEY",
            extra_env={},
            api_hosts=("api.example.com",),
        )
        mapping = {
            "api.example.com": ["1.2.3.4"],
            "pypi.org": ["5.6.7.8"],
            "files.pythonhosted.org": ["9.10.11.12"],
        }
        with patch("socket.getaddrinfo", side_effect=self._fake_getaddrinfo(mapping)):
            cidrs = _resolve_egress_cidrs(config)

        assert cidrs == ["1.2.3.4/32", "5.6.7.8/32", "9.10.11.12/32"]

    def test_deduplicates_ips(self):
        config = AgentSandboxConfig(
            npm_package="test-agent",
            skills_path=".test/skills",
            run_cmd=("test",),
            key_env_var="TEST_KEY",
            extra_env={},
            api_hosts=("api.example.com",),
        )
        # Same IP returned for multiple hosts
        mapping = {
            "api.example.com": ["1.2.3.4", "1.2.3.4"],
            "pypi.org": ["1.2.3.4"],
            "files.pythonhosted.org": ["5.6.7.8"],
        }
        with patch("socket.getaddrinfo", side_effect=self._fake_getaddrinfo(mapping)):
            cidrs = _resolve_egress_cidrs(config)

        assert cidrs == ["1.2.3.4/32", "5.6.7.8/32"]

    def test_dns_failure_does_not_raise(self):
        config = AgentSandboxConfig(
            npm_package="test-agent",
            skills_path=".test/skills",
            run_cmd=("test",),
            key_env_var="TEST_KEY",
            extra_env={},
            api_hosts=("unreachable.invalid",),
        )
        # All hosts fail DNS resolution
        with patch(
            "socket.getaddrinfo",
            side_effect=socket.gaierror("Name or service not known"),
        ):
            cidrs = _resolve_egress_cidrs(config)

        # Should return empty list, not raise
        assert cidrs == []

    def test_partial_dns_failure_returns_resolved_hosts(self):
        config = AgentSandboxConfig(
            npm_package="test-agent",
            skills_path=".test/skills",
            run_cmd=("test",),
            key_env_var="TEST_KEY",
            extra_env={},
            api_hosts=("api.example.com",),
        )
        mapping = {
            "api.example.com": ["1.2.3.4"],
            # pypi.org fails, files.pythonhosted.org succeeds
            "files.pythonhosted.org": ["5.6.7.8"],
        }
        with patch("socket.getaddrinfo", side_effect=self._fake_getaddrinfo(mapping)):
            cidrs = _resolve_egress_cidrs(config)

        assert "1.2.3.4/32" in cidrs
        assert "5.6.7.8/32" in cidrs

    def test_multiple_ips_per_host(self):
        config = AgentSandboxConfig(
            npm_package="test-agent",
            skills_path=".test/skills",
            run_cmd=("test",),
            key_env_var="TEST_KEY",
            extra_env={},
            api_hosts=("cdn.example.com",),
        )
        mapping = {
            "cdn.example.com": ["1.1.1.1", "1.0.0.1"],
            "pypi.org": ["5.6.7.8"],
            "files.pythonhosted.org": ["9.10.11.12"],
        }
        with patch("socket.getaddrinfo", side_effect=self._fake_getaddrinfo(mapping)):
            cidrs = _resolve_egress_cidrs(config)

        assert "1.1.1.1/32" in cidrs
        assert "1.0.0.1/32" in cidrs


class TestAgentConfigsHaveApiHosts:
    """Every agent config must declare API hosts for network egress."""

    @pytest.mark.parametrize("agent_name", list(AGENT_CONFIGS.keys()))
    def test_agent_has_api_hosts(self, agent_name: str):
        config = AGENT_CONFIGS[agent_name]
        assert len(config.api_hosts) > 0, f"Agent '{agent_name}' has no api_hosts"

    def test_infra_hosts_not_empty(self):
        assert len(_INFRA_HOSTS) > 0
