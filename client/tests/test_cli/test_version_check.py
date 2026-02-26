"""Tests for dhub.cli.version_check -- PyPI version check with caching."""

import json
import time

import httpx
import respx
from rich.console import Console

from dhub.cli.version_check import (
    _CACHE_TTL_SECONDS,
    _PYPI_URL,
    _parse_semver,
    _read_cache,
    _write_cache,
    get_latest_version,
    show_update_notice,
)


class TestParseSemver:
    def test_basic(self):
        assert _parse_semver("1.2.3") == (1, 2, 3)

    def test_comparison(self):
        assert _parse_semver("0.9.0") > _parse_semver("0.8.0")
        assert _parse_semver("1.0.0") > _parse_semver("0.99.99")
        assert _parse_semver("0.8.0") == _parse_semver("0.8.0")


class TestCache:
    def test_read_empty_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr("dhub.cli.version_check._cache_path", lambda: tmp_path / ".version_cache.json")
        assert _read_cache() is None

    def test_write_and_read_cache(self, tmp_path, monkeypatch):
        cache_file = tmp_path / ".version_cache.json"
        monkeypatch.setattr("dhub.cli.version_check._cache_path", lambda: cache_file)

        _write_cache("0.9.0")
        assert _read_cache() == "0.9.0"

    def test_expired_cache_returns_none(self, tmp_path, monkeypatch):
        cache_file = tmp_path / ".version_cache.json"
        monkeypatch.setattr("dhub.cli.version_check._cache_path", lambda: cache_file)

        # Write cache with old timestamp
        cache_file.write_text(
            json.dumps({"latest_version": "0.9.0", "checked_at": time.time() - _CACHE_TTL_SECONDS - 1})
        )
        assert _read_cache() is None

    def test_corrupted_cache_returns_none(self, tmp_path, monkeypatch):
        cache_file = tmp_path / ".version_cache.json"
        monkeypatch.setattr("dhub.cli.version_check._cache_path", lambda: cache_file)

        cache_file.write_text("not json!!")
        assert _read_cache() is None


class TestGetLatestVersion:
    @respx.mock
    def test_fetches_from_pypi_when_no_cache(self, tmp_path, monkeypatch):
        cache_file = tmp_path / ".version_cache.json"
        monkeypatch.setattr("dhub.cli.version_check._cache_path", lambda: cache_file)

        respx.get(_PYPI_URL).mock(return_value=httpx.Response(200, json={"info": {"version": "0.9.0"}}))

        result = get_latest_version()
        assert result == "0.9.0"
        # Should also be cached now
        assert _read_cache() == "0.9.0"

    @respx.mock
    def test_uses_cache_when_fresh(self, tmp_path, monkeypatch):
        cache_file = tmp_path / ".version_cache.json"
        monkeypatch.setattr("dhub.cli.version_check._cache_path", lambda: cache_file)

        _write_cache("0.9.0")

        # This route should NOT be hit
        route = respx.get(_PYPI_URL).mock(return_value=httpx.Response(200, json={"info": {"version": "1.0.0"}}))

        result = get_latest_version()
        assert result == "0.9.0"  # Cached value, not the PyPI value
        assert not route.called

    @respx.mock
    def test_returns_none_on_pypi_error(self, tmp_path, monkeypatch):
        cache_file = tmp_path / ".version_cache.json"
        monkeypatch.setattr("dhub.cli.version_check._cache_path", lambda: cache_file)

        respx.get(_PYPI_URL).mock(return_value=httpx.Response(500))

        result = get_latest_version()
        assert result is None


class TestShowUpdateNotice:
    def test_shows_panel_when_update_available(self, tmp_path, monkeypatch):
        cache_file = tmp_path / ".version_cache.json"
        monkeypatch.setattr("dhub.cli.version_check._cache_path", lambda: cache_file)
        monkeypatch.setattr("dhub.cli.config.get_client_version", lambda: "0.8.0")
        monkeypatch.delenv("DHUB_NO_UPDATE_CHECK", raising=False)

        _write_cache("0.9.0")

        console = Console(record=True, width=80)
        show_update_notice(console)

        output = console.export_text()
        assert "dhub update available!" in output
        assert "0.8.0" in output
        assert "0.9.0" in output
        assert "dhub upgrade" in output

    def test_no_output_when_up_to_date(self, tmp_path, monkeypatch):
        cache_file = tmp_path / ".version_cache.json"
        monkeypatch.setattr("dhub.cli.version_check._cache_path", lambda: cache_file)
        monkeypatch.setattr("dhub.cli.config.get_client_version", lambda: "0.8.0")
        monkeypatch.delenv("DHUB_NO_UPDATE_CHECK", raising=False)

        _write_cache("0.8.0")

        console = Console(record=True, width=80)
        show_update_notice(console)

        output = console.export_text()
        assert "update available" not in output

    def test_opt_out_via_env_var(self, tmp_path, monkeypatch):
        cache_file = tmp_path / ".version_cache.json"
        monkeypatch.setattr("dhub.cli.version_check._cache_path", lambda: cache_file)
        monkeypatch.setenv("DHUB_NO_UPDATE_CHECK", "1")

        _write_cache("99.0.0")

        console = Console(record=True, width=80)
        show_update_notice(console)

        output = console.export_text()
        assert "update available" not in output

    def test_silent_on_error(self, tmp_path, monkeypatch):
        """Version check should never crash the CLI."""
        monkeypatch.setattr(
            "dhub.cli.version_check.get_latest_version",
            lambda: (_ for _ in ()).throw(RuntimeError("network down")),
        )
        monkeypatch.delenv("DHUB_NO_UPDATE_CHECK", raising=False)

        console = Console(record=True, width=80)
        # Should not raise
        show_update_notice(console)
