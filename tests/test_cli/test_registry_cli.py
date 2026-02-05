"""Tests for decision_hub.cli.registry -- publish and install commands."""

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from decision_hub.cli.app import app

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

    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.registry.httpx.Client")
    def test_publish_success(
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
            ["publish", str(tmp_path), "--org", "myorg", "--name", "my-skill", "--version", "1.0.0"],
        )

        assert result.exit_code == 0
        assert "Published: myorg/my-skill@1.0.0" in result.output

    def test_publish_missing_skill_md(self, tmp_path: Path) -> None:
        """Publish should fail when SKILL.md is absent."""
        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--org", "myorg", "--name", "my-skill", "--version", "1.0.0"],
        )

        assert result.exit_code == 1
        assert "SKILL.md not found" in result.output

    def test_publish_invalid_skill_name(self, tmp_path: Path) -> None:
        """Publish should fail with an invalid skill name."""
        _write_skill_md(tmp_path)

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--org", "myorg", "--name", "INVALID NAME!", "--version", "1.0.0"],
        )

        # validate_skill_name raises ValueError which propagates
        assert result.exit_code != 0

    def test_publish_invalid_semver(self, tmp_path: Path) -> None:
        """Publish should fail with an invalid semver string."""
        _write_skill_md(tmp_path)

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--org", "myorg", "--name", "my-skill", "--version", "not-a-version"],
        )

        assert result.exit_code != 0

    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.registry.httpx.Client")
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
            ["publish", str(tmp_path), "--org", "myorg", "--name", "my-skill", "--version", "1.0.0"],
        )

        assert result.exit_code == 1
        assert "already exists" in result.output


# ---------------------------------------------------------------------------
# install_command
# ---------------------------------------------------------------------------

class TestInstallCommand:

    @patch("decision_hub.domain.install.verify_checksum")
    @patch("decision_hub.domain.install.get_dhub_skill_path")
    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.registry.httpx.Client")
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

    def test_install_invalid_skill_ref(self) -> None:
        """Install should reject a skill reference without a slash."""
        result = runner.invoke(app, ["install", "no-slash"])

        assert result.exit_code == 1
        assert "org/skill format" in result.output

    @patch("decision_hub.domain.install.get_dhub_skill_path")
    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.registry.httpx.Client")
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

    @patch("decision_hub.domain.install.link_skill_to_agent", return_value=Path("/mock/link"))
    @patch("decision_hub.domain.install.verify_checksum")
    @patch("decision_hub.domain.install.get_dhub_skill_path")
    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.registry.httpx.Client")
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

    @patch("decision_hub.domain.install.link_skill_to_all_agents", return_value=["claude", "cursor"])
    @patch("decision_hub.domain.install.verify_checksum")
    @patch("decision_hub.domain.install.get_dhub_skill_path")
    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.registry.httpx.Client")
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
