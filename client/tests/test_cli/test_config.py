"""Tests for dhub.cli.config -- CLI configuration management."""

import json

import click
import pytest

from dhub.cli.config import CliConfig, load_config, save_config


class TestLoadConfig:
    """load_config should handle missing, valid, and corrupted config files."""

    def test_returns_defaults_when_no_file(self, tmp_path, monkeypatch):
        """Missing config file returns default CliConfig."""
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")

        config = load_config()

        assert config.token is None
        assert "dev" in config.api_url

    def test_loads_valid_config(self, tmp_path, monkeypatch):
        """Valid JSON config file is loaded correctly."""
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")

        config_path = tmp_path / "config.dev.json"
        config_path.write_text(
            json.dumps({"api_url": "https://example.com", "token": "tok123"})
        )

        config = load_config()

        assert config.api_url == "https://example.com"
        assert config.token == "tok123"

    def test_corrupted_json_exits_gracefully(self, tmp_path, monkeypatch):
        """Corrupted JSON should exit with code 1, not crash with a traceback."""
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")

        config_path = tmp_path / "config.dev.json"
        config_path.write_text("{invalid json!!")

        with pytest.raises(click.exceptions.Exit):
            load_config()

    def test_empty_file_exits_gracefully(self, tmp_path, monkeypatch):
        """Empty config file should exit with code 1."""
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")

        config_path = tmp_path / "config.dev.json"
        config_path.write_text("")

        with pytest.raises(click.exceptions.Exit):
            load_config()


class TestSaveConfig:
    """save_config should persist config to the correct env-specific file."""

    def test_round_trip(self, tmp_path, monkeypatch):
        """Saved config should be loadable."""
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")

        original = CliConfig(api_url="https://test.example.com", token="secret")
        save_config(original)

        loaded = load_config()

        assert loaded.api_url == original.api_url
        assert loaded.token == original.token

    def test_round_trip_with_orgs(self, tmp_path, monkeypatch):
        """Saved config with orgs and default_org should round-trip."""
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")

        original = CliConfig(
            api_url="https://test.example.com",
            token="secret",
            orgs=("alice", "pymc-labs"),
            default_org="pymc-labs",
        )
        save_config(original)

        loaded = load_config()

        assert loaded.orgs == ("alice", "pymc-labs")
        assert loaded.default_org == "pymc-labs"

    def test_backward_compat_no_orgs_field(self, tmp_path, monkeypatch):
        """Loading old config without orgs field should use defaults."""
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")

        config_path = tmp_path / "config.dev.json"
        config_path.write_text(
            json.dumps({"api_url": "https://example.com", "token": "old-tok"})
        )

        loaded = load_config()

        assert loaded.orgs == ()
        assert loaded.default_org is None
        assert loaded.token == "old-tok"


class TestGetToken:
    """get_token should check DHUB_TOKEN env var first."""

    def test_env_var_overrides_config(self, monkeypatch):
        """DHUB_TOKEN env var should take priority over config."""
        from dhub.cli.config import get_token

        monkeypatch.setenv("DHUB_TOKEN", "env-token-123")

        result = get_token()

        assert result == "env-token-123"


class TestGetDefaultOrg:
    """get_default_org should check DHUB_DEFAULT_ORG env var first."""

    def test_env_var_overrides_config(self, tmp_path, monkeypatch):
        """DHUB_DEFAULT_ORG env var should take priority."""
        from dhub.cli.config import get_default_org

        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")
        monkeypatch.setenv("DHUB_DEFAULT_ORG", "env-org")

        result = get_default_org()

        assert result == "env-org"

    def test_falls_back_to_config(self, tmp_path, monkeypatch):
        """Should fall back to config when env var not set."""
        from dhub.cli.config import get_default_org

        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")
        monkeypatch.delenv("DHUB_DEFAULT_ORG", raising=False)

        config_path = tmp_path / "config.dev.json"
        config_path.write_text(
            json.dumps({
                "api_url": "https://example.com",
                "token": "tok",
                "default_org": "config-org",
            })
        )

        result = get_default_org()

        assert result == "config-org"

    def test_returns_none_when_unset(self, tmp_path, monkeypatch):
        """Should return None when neither env var nor config is set."""
        from dhub.cli.config import get_default_org

        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")
        monkeypatch.delenv("DHUB_DEFAULT_ORG", raising=False)

        result = get_default_org()

        assert result is None
