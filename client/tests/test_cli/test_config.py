"""Tests for dhub.cli.config -- CLI configuration management."""

import json
import os
import sys
from stat import S_IMODE

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
        config_path.write_text(json.dumps({"api_url": "https://example.com", "token": "tok123"}))

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
        config_path.write_text(json.dumps({"api_url": "https://example.com", "token": "old-tok"}))

        loaded = load_config()

        assert loaded.orgs == ()
        assert loaded.default_org is None
        assert loaded.token == "old-tok"

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
    def test_token_file_is_user_only_readable(self, tmp_path, monkeypatch):
        """Saved config containing a token must not be world-readable.

        Multi-user hosts (CI runners, shared dev boxes) would otherwise
        leak the user's API token to any other local user.
        """
        config_dir = tmp_path / "dhub-test"
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", config_dir)
        monkeypatch.setenv("DHUB_ENV", "dev")

        save_config(CliConfig(api_url="https://example.com", token="super-secret"))

        path = config_dir / "config.dev.json"
        assert S_IMODE(path.stat().st_mode) == 0o600
        assert S_IMODE(config_dir.stat().st_mode) == 0o700

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX file permissions")
    def test_overwrite_tightens_loose_permissions(self, tmp_path, monkeypatch):
        """If a pre-existing file is world-readable, save_config should fix it."""
        config_dir = tmp_path / "dhub-test"
        config_dir.mkdir()
        path = config_dir / "config.dev.json"
        path.write_text("{}")
        path.chmod(0o644)

        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", config_dir)
        monkeypatch.setenv("DHUB_ENV", "dev")

        save_config(CliConfig(api_url="https://example.com", token="tok"))

        assert S_IMODE(path.stat().st_mode) == 0o600

    def test_no_partial_tmp_file_left_on_write_failure(self, tmp_path, monkeypatch):
        """If the write step fails after the tmp file was opened, it must be cleaned up.

        Guards against accumulating partial token files in ~/.dhub/ when
        the disk fills mid-write.
        """
        config_dir = tmp_path / "dhub-test"
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", config_dir)
        monkeypatch.setenv("DHUB_ENV", "dev")

        real_fdopen = os.fdopen

        def _failing_fdopen(fd, *args, **kwargs):
            # Wrap the real file object so write() raises but the fd is
            # still closed properly when the context manager unwinds.
            handle = real_fdopen(fd, *args, **kwargs)

            class _Wrapper:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *exc):
                    handle.close()
                    return False

                def write(self_inner, _data):
                    raise OSError("disk full")

            return _Wrapper()

        monkeypatch.setattr("dhub.cli.config.os.fdopen", _failing_fdopen)

        with pytest.raises(OSError):
            save_config(CliConfig(api_url="https://example.com", token="tok"))

        leftover = list(config_dir.glob("*.tmp")) if config_dir.exists() else []
        assert leftover == []


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
            json.dumps(
                {
                    "api_url": "https://example.com",
                    "token": "tok",
                    "default_org": "config-org",
                }
            )
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
