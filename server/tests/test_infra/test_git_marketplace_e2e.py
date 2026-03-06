"""End-to-end test: verify git clone works against the virtual marketplace.

This test builds a MemoryRepo, serves it via the dulwich WSGI handler,
and runs `git clone` against it using a local WSGI test server.
"""

import json
import subprocess
import tempfile
import threading
from pathlib import Path
from wsgiref.simple_server import make_server

import pytest

from decision_hub.domain.marketplace import SkillPluginEntry
from decision_hub.infra.git_marketplace import (
    build_marketplace_repo,
    create_git_wsgi_app,
)


@pytest.fixture
def sample_entries():
    return [
        SkillPluginEntry(
            org_slug="test-org",
            skill_name="test-skill",
            version="1.0.0",
            description="A test skill for E2E",
            category="testing",
            gauntlet_grade="A",
            eval_status="passed",
            download_count=42,
        ),
    ]


@pytest.fixture
def sample_skill_md():
    return {"test-org/test-skill": "---\nname: test-skill\n---\nTest skill prompt content"}


@pytest.fixture
def git_server(sample_entries, sample_skill_md):
    """Start a local WSGI server serving the virtual git repo."""
    repo = build_marketplace_repo(sample_entries, sample_skill_md)
    wsgi_app = create_git_wsgi_app(repo_builder=lambda: repo)

    server = make_server("127.0.0.1", 0, wsgi_app)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def test_git_clone_marketplace(git_server):
    """Verify that `git clone` succeeds and produces expected file structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        clone_dir = Path(tmpdir) / "marketplace"
        result = subprocess.run(
            ["git", "clone", f"{git_server}/", str(clone_dir)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"git clone failed: {result.stderr}"

        # Verify marketplace.json
        mj = clone_dir / ".claude-plugin" / "marketplace.json"
        assert mj.exists(), f"marketplace.json not found. Files: {list(clone_dir.rglob('*'))}"
        marketplace = json.loads(mj.read_text())
        assert marketplace["name"] == "decision-hub"
        assert len(marketplace["plugins"]) == 1
        assert marketplace["plugins"][0]["name"] == "test-org--test-skill"

        # Verify plugin structure
        plugin_dir = clone_dir / "plugins" / "test-org--test-skill"
        assert (plugin_dir / ".claude-plugin" / "plugin.json").exists()
        plugin_json = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text())
        assert plugin_json["version"] == "1.0.0"

        # Verify SKILL.md
        skill_md_path = plugin_dir / "skills" / "test-skill" / "SKILL.md"
        assert skill_md_path.exists()
        assert "Test skill prompt content" in skill_md_path.read_text()
