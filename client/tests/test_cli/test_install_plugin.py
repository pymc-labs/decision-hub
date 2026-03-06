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

    cache_dir = tmp_path / ".claude" / "plugins" / "cache" / "decision-hub" / "org" / "test-plugin" / "1.0.0"
    assert (cache_dir / "plugin.json").exists()


def test_plugin_path_includes_org():
    """Plugin install path must include org to avoid cross-org collisions."""
    from dhub.core.install import get_dhub_plugin_path

    path = get_dhub_plugin_path("acme", "my-plugin", "1.0.0")
    assert "acme" in path.parts
    # Two different orgs should get different paths
    path2 = get_dhub_plugin_path("other-org", "my-plugin", "1.0.0")
    assert path != path2
