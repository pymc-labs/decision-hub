"""Tests for dhub.cli.config -- CLI configuration management."""

import json
import os
import stat
import sys

import click
import pytest

from dhub.cli.config import (
    CliConfig,
    is_config_file_secure,
    load_config,
    save_config,
)


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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission semantics")
class TestSaveConfigSecurity:
    """save_config must produce an atomic, owner-only file.

    The config file contains a long-lived bearer token; the default
    umask of 0o022 would leave it world-readable on shared systems.
    Non-atomic writes also risk leaving a half-written file behind if
    the process is killed, which forces the user to delete the file
    and re-authenticate.
    """

    def test_config_file_is_owner_read_write_only(self, tmp_path, monkeypatch):
        """Saved file must have mode 0o600."""
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")

        save_config(CliConfig(api_url="https://example.com", token="secret"))

        path = tmp_path / "config.dev.json"
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

    def test_overwriting_existing_loose_file_tightens_perms(self, tmp_path, monkeypatch):
        """A pre-existing 0o644 file is replaced by a 0o600 one."""
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")

        # Simulate a config left behind by an older CLI version.
        path = tmp_path / "config.dev.json"
        path.write_text(json.dumps({"api_url": "https://old.example.com"}))
        path.chmod(0o644)

        save_config(CliConfig(api_url="https://new.example.com", token="t"))

        mode = path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_save_is_atomic(self, tmp_path, monkeypatch):
        """Crash mid-write must leave the existing file intact.

        We simulate a crash by patching ``os.fdopen`` to raise after
        the tempfile is created but before the rename. The original
        config — the one ``load_config`` would read — must be unchanged.
        """
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")

        # Seed an original config we expect to survive.
        save_config(CliConfig(api_url="https://stable.example.com", token="original"))
        path = tmp_path / "config.dev.json"
        original_bytes = path.read_bytes()

        # Now make the next write blow up partway through.
        real_fdopen = os.fdopen

        def boom(*args, **kwargs):
            # Close the fd so we don't leak it, then raise.
            fh = real_fdopen(*args, **kwargs)
            fh.close()
            raise OSError("simulated disk full")

        monkeypatch.setattr("dhub.cli.config.os.fdopen", boom)

        with pytest.raises(OSError, match="simulated disk full"):
            save_config(CliConfig(api_url="https://overwrite.example.com", token="new"))

        # Original file is byte-for-byte intact — no truncation, no
        # corruption, and load_config still returns the old config.
        assert path.read_bytes() == original_bytes
        loaded = load_config()
        assert loaded.token == "original"
        assert loaded.api_url == "https://stable.example.com"

        # No tempfile garbage left behind.
        leftover = [p for p in tmp_path.iterdir() if p.name.startswith(".config.dev.json.") and p.name.endswith(".tmp")]
        assert leftover == [], f"tempfile not cleaned up: {leftover}"

    def test_config_dir_is_owner_only(self, tmp_path, monkeypatch):
        """The ~/.dhub directory should also be 0o700 when we create it."""
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")

        save_config(CliConfig(api_url="https://example.com", token="t"))

        mode = tmp_path.stat().st_mode & 0o777
        # tmp_path itself may have stricter mode set by pytest, so we
        # assert that no group/other bits are set rather than ==0o700.
        assert (mode & (stat.S_IRWXG | stat.S_IRWXO)) == 0


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission semantics")
class TestIsConfigFileSecure:
    """``is_config_file_secure`` is used by ``dhub doctor`` to warn users."""

    def test_returns_true_when_owner_only(self, tmp_path, monkeypatch):
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")
        save_config(CliConfig(token="t"))
        assert is_config_file_secure() is True

    def test_returns_false_when_world_readable(self, tmp_path, monkeypatch):
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")
        save_config(CliConfig(token="t"))
        (tmp_path / "config.dev.json").chmod(0o644)
        assert is_config_file_secure() is False

    def test_returns_true_when_file_missing(self, tmp_path, monkeypatch):
        """A non-existent file is vacuously secure."""
        monkeypatch.setattr("dhub.cli.config.CONFIG_DIR", tmp_path)
        monkeypatch.setenv("DHUB_ENV", "dev")
        assert is_config_file_secure() is True
