"""Tests for dhub.cli.registry -- publish, install, list, and delete commands."""

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(response: MagicMock) -> MagicMock:
    """Return a mock httpx.Client usable as a context manager."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post.return_value = response
    client.get.return_value = response
    return client


def _ok_response(json_data: dict | None = None, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status = MagicMock()
    return resp


def _error_response(status_code: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


def _write_skill_md(directory: Path) -> None:
    """Write a minimal valid SKILL.md to *directory*."""
    (directory / "SKILL.md").write_text(
        "---\nname: test-skill\ndescription: A test skill\n---\nBody text\n"
    )


def _make_zip_bytes() -> bytes:
    """Create a small in-memory zip archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\nname: s\ndescription: d\n---\nbody\n")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# publish_command
# ---------------------------------------------------------------------------

class TestPublishCommand:

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_publish_success_explicit_version(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
        tmp_path: Path,
    ) -> None:
        _write_skill_md(tmp_path)
        mock_client_cls.return_value = _make_mock_client(_ok_response())

        result = runner.invoke(
            app,
            ["publish", "myorg/my-skill", str(tmp_path), "--version", "1.0.0"],
        )

        assert result.exit_code == 0
        assert "Published: myorg/my-skill@1.0.0" in result.output

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_publish_auto_bump_first_publish(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
        tmp_path: Path,
    ) -> None:
        """First publish with no --version should default to 0.1.0."""
        _write_skill_md(tmp_path)

        # First call: latest-version returns 404, second call: publish succeeds
        latest_resp = _error_response(404)
        publish_resp = _ok_response()

        client_latest = MagicMock()
        client_latest.__enter__ = MagicMock(return_value=client_latest)
        client_latest.__exit__ = MagicMock(return_value=False)
        client_latest.get.return_value = latest_resp

        client_publish = MagicMock()
        client_publish.__enter__ = MagicMock(return_value=client_publish)
        client_publish.__exit__ = MagicMock(return_value=False)
        client_publish.post.return_value = publish_resp

        mock_client_cls.side_effect = [client_latest, client_publish]

        result = runner.invoke(
            app,
            ["publish", "myorg/my-skill", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert "0.1.0" in result.output
        assert "Published: myorg/my-skill@0.1.0" in result.output

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_publish_auto_bump_patch(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Auto-bump patch: 1.2.3 -> 1.2.4."""
        _write_skill_md(tmp_path)

        latest_resp = _ok_response(json_data={"version": "1.2.3"})
        publish_resp = _ok_response()

        client_latest = MagicMock()
        client_latest.__enter__ = MagicMock(return_value=client_latest)
        client_latest.__exit__ = MagicMock(return_value=False)
        client_latest.get.return_value = latest_resp

        client_publish = MagicMock()
        client_publish.__enter__ = MagicMock(return_value=client_publish)
        client_publish.__exit__ = MagicMock(return_value=False)
        client_publish.post.return_value = publish_resp

        mock_client_cls.side_effect = [client_latest, client_publish]

        result = runner.invoke(
            app,
            ["publish", "myorg/my-skill", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert "1.2.4" in result.output
        assert "Published: myorg/my-skill@1.2.4" in result.output

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_publish_auto_bump_minor(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Auto-bump minor: 1.2.3 -> 1.3.0."""
        _write_skill_md(tmp_path)

        latest_resp = _ok_response(json_data={"version": "1.2.3"})
        publish_resp = _ok_response()

        client_latest = MagicMock()
        client_latest.__enter__ = MagicMock(return_value=client_latest)
        client_latest.__exit__ = MagicMock(return_value=False)
        client_latest.get.return_value = latest_resp

        client_publish = MagicMock()
        client_publish.__enter__ = MagicMock(return_value=client_publish)
        client_publish.__exit__ = MagicMock(return_value=False)
        client_publish.post.return_value = publish_resp

        mock_client_cls.side_effect = [client_latest, client_publish]

        result = runner.invoke(
            app,
            ["publish", "myorg/my-skill", str(tmp_path), "--minor"],
        )

        assert result.exit_code == 0
        assert "1.3.0" in result.output
        assert "Published: myorg/my-skill@1.3.0" in result.output

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_publish_auto_bump_major(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Auto-bump major: 1.2.3 -> 2.0.0."""
        _write_skill_md(tmp_path)

        latest_resp = _ok_response(json_data={"version": "1.2.3"})
        publish_resp = _ok_response()

        client_latest = MagicMock()
        client_latest.__enter__ = MagicMock(return_value=client_latest)
        client_latest.__exit__ = MagicMock(return_value=False)
        client_latest.get.return_value = latest_resp

        client_publish = MagicMock()
        client_publish.__enter__ = MagicMock(return_value=client_publish)
        client_publish.__exit__ = MagicMock(return_value=False)
        client_publish.post.return_value = publish_resp

        mock_client_cls.side_effect = [client_latest, client_publish]

        result = runner.invoke(
            app,
            ["publish", "myorg/my-skill", str(tmp_path), "--major"],
        )

        assert result.exit_code == 0
        assert "2.0.0" in result.output
        assert "Published: myorg/my-skill@2.0.0" in result.output

    def test_publish_missing_skill_md(self, tmp_path: Path) -> None:
        """Publish should fail when SKILL.md is absent."""
        result = runner.invoke(
            app,
            ["publish", "myorg/my-skill", str(tmp_path), "--version", "1.0.0"],
        )

        assert result.exit_code == 1
        assert "SKILL.md not found" in result.output

    def test_publish_invalid_skill_name(self, tmp_path: Path) -> None:
        """Publish should fail with an invalid skill name."""
        _write_skill_md(tmp_path)

        result = runner.invoke(
            app,
            ["publish", "myorg/INVALID NAME!", str(tmp_path), "--version", "1.0.0"],
        )

        # validate_skill_name raises ValueError which propagates
        assert result.exit_code != 0

    def test_publish_invalid_semver(self, tmp_path: Path) -> None:
        """Publish should fail with an invalid semver string."""
        _write_skill_md(tmp_path)

        result = runner.invoke(
            app,
            ["publish", "myorg/my-skill", str(tmp_path), "--version", "not-a-version"],
        )

        assert result.exit_code != 0

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_publish_409_conflict(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
        tmp_path: Path,
    ) -> None:
        _write_skill_md(tmp_path)
        mock_client_cls.return_value = _make_mock_client(_error_response(409))

        result = runner.invoke(
            app,
            ["publish", "myorg/my-skill", str(tmp_path), "--version", "1.0.0"],
        )

        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_publish_multiple_bump_flags_rejected(self, tmp_path: Path) -> None:
        """Specifying multiple bump flags should fail."""
        _write_skill_md(tmp_path)

        result = runner.invoke(
            app,
            ["publish", "myorg/my-skill", str(tmp_path), "--minor", "--major"],
        )

        assert result.exit_code == 1
        assert "Only one" in result.output


# ---------------------------------------------------------------------------
# install_command
# ---------------------------------------------------------------------------

class TestInstallCommand:

    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_install_success(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
        mock_skill_path: MagicMock,
        mock_checksum: MagicMock,
        tmp_path: Path,
    ) -> None:
        skill_dir = tmp_path / "myorg" / "my-skill"
        mock_skill_path.return_value = skill_dir

        zip_bytes = _make_zip_bytes()

        # Resolve response
        resolve_resp = _ok_response({
            "version": "1.0.0",
            "download_url": "http://test:8000/download/skill.zip",
            "checksum": "abc123",
        })
        # Download response
        download_resp = MagicMock()
        download_resp.status_code = 200
        download_resp.content = zip_bytes
        download_resp.raise_for_status = MagicMock()

        # The install command opens two separate httpx.Client() blocks
        mock_client_resolve = MagicMock()
        mock_client_resolve.__enter__ = MagicMock(return_value=mock_client_resolve)
        mock_client_resolve.__exit__ = MagicMock(return_value=False)
        mock_client_resolve.get.return_value = resolve_resp

        mock_client_download = MagicMock()
        mock_client_download.__enter__ = MagicMock(return_value=mock_client_download)
        mock_client_download.__exit__ = MagicMock(return_value=False)
        mock_client_download.get.return_value = download_resp

        mock_client_cls.side_effect = [mock_client_resolve, mock_client_download]

        result = runner.invoke(app, ["install", "myorg/my-skill"])

        assert result.exit_code == 0
        assert "Installed myorg/my-skill@1.0.0" in result.output
        mock_checksum.assert_called_once_with(zip_bytes, "abc123")
        # Verify the zip was extracted
        assert skill_dir.exists()

    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_install_with_allow_risky_flag(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
        mock_skill_path: MagicMock,
        mock_checksum: MagicMock,
        tmp_path: Path,
    ) -> None:
        """--allow-risky flag passes allow_risky=true to resolve request."""
        skill_dir = tmp_path / "myorg" / "my-skill"
        mock_skill_path.return_value = skill_dir

        zip_bytes = _make_zip_bytes()

        resolve_resp = _ok_response({
            "version": "1.0.0",
            "download_url": "http://test:8000/download/skill.zip",
            "checksum": "abc123",
        })
        download_resp = MagicMock()
        download_resp.status_code = 200
        download_resp.content = zip_bytes
        download_resp.raise_for_status = MagicMock()

        mock_client_resolve = MagicMock()
        mock_client_resolve.__enter__ = MagicMock(return_value=mock_client_resolve)
        mock_client_resolve.__exit__ = MagicMock(return_value=False)
        mock_client_resolve.get.return_value = resolve_resp

        mock_client_download = MagicMock()
        mock_client_download.__enter__ = MagicMock(return_value=mock_client_download)
        mock_client_download.__exit__ = MagicMock(return_value=False)
        mock_client_download.get.return_value = download_resp

        mock_client_cls.side_effect = [mock_client_resolve, mock_client_download]

        result = runner.invoke(
            app, ["install", "myorg/my-skill", "--allow-risky"]
        )

        assert result.exit_code == 0
        # Verify allow_risky was passed in the resolve request params
        resolve_call = mock_client_resolve.get.call_args
        params = resolve_call.kwargs.get("params", {})
        assert params.get("allow_risky") == "true"

    def test_install_invalid_skill_ref(self) -> None:
        """Install should reject a skill reference without a slash."""
        result = runner.invoke(app, ["install", "no-slash"])

        assert result.exit_code == 1
        assert "org/skill format" in result.output

    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_install_404_not_found(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
        mock_skill_path: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_skill_path.return_value = tmp_path / "org" / "skill"
        mock_client_cls.return_value = _make_mock_client(_error_response(404))

        result = runner.invoke(app, ["install", "org/skill"])

        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("dhub.core.install.link_skill_to_agent", return_value=Path("/mock/link"))
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_install_with_agent_flag(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
        mock_skill_path: MagicMock,
        mock_checksum: MagicMock,
        mock_link: MagicMock,
        tmp_path: Path,
    ) -> None:
        skill_dir = tmp_path / "myorg" / "my-skill"
        mock_skill_path.return_value = skill_dir
        zip_bytes = _make_zip_bytes()

        resolve_resp = _ok_response({
            "version": "2.0.0",
            "download_url": "http://test:8000/download/skill.zip",
            "checksum": "def456",
        })
        download_resp = MagicMock()
        download_resp.status_code = 200
        download_resp.content = zip_bytes
        download_resp.raise_for_status = MagicMock()

        mock_client_resolve = MagicMock()
        mock_client_resolve.__enter__ = MagicMock(return_value=mock_client_resolve)
        mock_client_resolve.__exit__ = MagicMock(return_value=False)
        mock_client_resolve.get.return_value = resolve_resp

        mock_client_download = MagicMock()
        mock_client_download.__enter__ = MagicMock(return_value=mock_client_download)
        mock_client_download.__exit__ = MagicMock(return_value=False)
        mock_client_download.get.return_value = download_resp

        mock_client_cls.side_effect = [mock_client_resolve, mock_client_download]

        result = runner.invoke(
            app, ["install", "myorg/my-skill", "--agent", "claude"]
        )

        assert result.exit_code == 0
        mock_link.assert_called_once_with("myorg", "my-skill", "claude")
        assert "Linked to claude" in result.output

    @patch("dhub.core.install.link_skill_to_all_agents", return_value=["claude", "cursor"])
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_install_with_agent_all(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
        mock_skill_path: MagicMock,
        mock_checksum: MagicMock,
        mock_link_all: MagicMock,
        tmp_path: Path,
    ) -> None:
        skill_dir = tmp_path / "myorg" / "my-skill"
        mock_skill_path.return_value = skill_dir
        zip_bytes = _make_zip_bytes()

        resolve_resp = _ok_response({
            "version": "3.0.0",
            "download_url": "http://test:8000/download/skill.zip",
            "checksum": "ghi789",
        })
        download_resp = MagicMock()
        download_resp.status_code = 200
        download_resp.content = zip_bytes
        download_resp.raise_for_status = MagicMock()

        mock_client_resolve = MagicMock()
        mock_client_resolve.__enter__ = MagicMock(return_value=mock_client_resolve)
        mock_client_resolve.__exit__ = MagicMock(return_value=False)
        mock_client_resolve.get.return_value = resolve_resp

        mock_client_download = MagicMock()
        mock_client_download.__enter__ = MagicMock(return_value=mock_client_download)
        mock_client_download.__exit__ = MagicMock(return_value=False)
        mock_client_download.get.return_value = download_resp

        mock_client_cls.side_effect = [mock_client_resolve, mock_client_download]

        result = runner.invoke(
            app, ["install", "myorg/my-skill", "--agent", "all"]
        )

        assert result.exit_code == 0
        mock_link_all.assert_called_once_with("myorg", "my-skill")
        assert "claude" in result.output
        assert "cursor" in result.output


# ---------------------------------------------------------------------------
# list_command
# ---------------------------------------------------------------------------

class TestListCommand:

    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_list_command(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
    ) -> None:
        """List displays a table when skills exist."""
        resp = _ok_response(
            json_data=[
                {
                    "org_slug": "acme",
                    "skill_name": "doc-writer",
                    "description": "Writes docs",
                    "latest_version": "1.0.0",
                    "updated_at": "2025-06-01",
                    "safety_rating": "A",
                    "author": "alice",
                },
            ],
        )
        mock_client_cls.return_value = _make_mock_client(resp)

        result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "Registry:" in result.output
        assert "http://test:8000" in result.output
        assert "Author" in result.output
        assert "acme" in result.output
        assert "doc-writer" in result.output
        assert "1.0.0" in result.output
        assert "alice" in result.output

    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_list_command_empty(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
    ) -> None:
        """List prints a message when no skills are published."""
        resp = _ok_response(json_data=[])
        mock_client_cls.return_value = _make_mock_client(resp)

        result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "Registry:" in result.output
        assert "No skills published yet" in result.output


# ---------------------------------------------------------------------------
# delete_command
# ---------------------------------------------------------------------------

class TestDeleteCommand:

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_delete_single_version_success(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        resp = _ok_response(status_code=200)
        mock_client.delete.return_value = resp
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            app, ["delete", "myorg/my-skill", "--version", "1.0.0"]
        )

        assert result.exit_code == 0
        assert "Deleted: myorg/my-skill@1.0.0" in result.output
        mock_client.delete.assert_called_once()

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_delete_all_versions_success(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        """Delete without --version should prompt confirmation and delete all."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        resp = _ok_response(
            json_data={"org_slug": "myorg", "skill_name": "my-skill", "versions_deleted": 3}
        )
        mock_client.delete.return_value = resp
        mock_client_cls.return_value = mock_client

        # 'y' confirms the prompt
        result = runner.invoke(
            app, ["delete", "myorg/my-skill"], input="y\n"
        )

        assert result.exit_code == 0
        assert "3 version(s)" in result.output
        mock_client.delete.assert_called_once()

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_delete_all_versions_aborted(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        """Delete all should abort if user declines confirmation."""
        result = runner.invoke(
            app, ["delete", "myorg/my-skill"], input="n\n"
        )

        assert result.exit_code == 1

    def test_delete_invalid_skill_ref(self) -> None:
        """Delete should reject a skill reference without a slash."""
        result = runner.invoke(
            app, ["delete", "no-slash", "--version", "1.0.0"]
        )

        assert result.exit_code == 1
        assert "org/skill format" in result.output

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_delete_404_not_found(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.delete.return_value = _error_response(404)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            app, ["delete", "myorg/my-skill", "--version", "9.9.9"]
        )

        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_delete_403_forbidden(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.delete.return_value = _error_response(403)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            app, ["delete", "myorg/my-skill", "--version", "1.0.0"]
        )

        assert result.exit_code == 1
        assert "permission" in result.output

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("dhub.cli.registry.httpx.Client")
    def test_delete_all_404_not_found(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        """Delete all for a non-existent skill should return error."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.delete.return_value = _error_response(404)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            app, ["delete", "myorg/no-skill"], input="y\n"
        )

        assert result.exit_code == 1
        assert "not found" in result.output
