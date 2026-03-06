"""Tests for plugin install to cache."""

import io
import zipfile

import pytest
from click.exceptions import Exit

from dhub.cli.registry import _install_plugin_to_cache


def test_install_plugin_to_cache_path_traversal(tmp_path, monkeypatch):
    """Zip with path traversal entries is rejected."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/malicious", "pwned")

    with pytest.raises(Exit):
        _install_plugin_to_cache("org", "plugin", "1.0.0", buf.getvalue())


def test_install_plugin_to_cache_creates_dir(tmp_path, monkeypatch):
    """Valid zip extracts to correct cache path."""
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("plugin.json", '{"name": "test"}')

    _install_plugin_to_cache("org", "test-plugin", "1.0.0", buf.getvalue())

    cache_dir = tmp_path / ".claude" / "plugins" / "cache" / "decision-hub" / "test-plugin" / "1.0.0"
    assert (cache_dir / "plugin.json").exists()
