"""Tests for dhub.cli.registry -- publish, install, list, and delete commands."""

import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx
import respx
from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_skill_md(directory: Path) -> None:
    """Write a minimal valid SKILL.md to *directory*."""
    (directory / "SKILL.md").write_text("---\nname: test-skill\ndescription: A test skill\n---\nBody text\n")


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
    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_success_explicit_version(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        tmp_path: Path,
    ) -> None:
        _write_skill_md(tmp_path)
        respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={}))

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--version", "1.0.0"],
        )

        assert result.exit_code == 0
        assert "Published: myorg/test-skill@1.0.0" in result.output

    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_auto_bump_first_publish(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        tmp_path: Path,
    ) -> None:
        """First publish with no --version should default to 0.1.0."""
        _write_skill_md(tmp_path)

        respx.get("http://test:8000/v1/skills/myorg/test-skill/latest-version").mock(return_value=httpx.Response(404))
        respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={}))

        result = runner.invoke(
            app,
            ["publish", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert "0.1.0" in result.output
        assert "Published: myorg/test-skill@0.1.0" in result.output

    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_auto_bump_patch(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        tmp_path: Path,
    ) -> None:
        """Auto-bump patch: 1.2.3 -> 1.2.4."""
        _write_skill_md(tmp_path)

        respx.get("http://test:8000/v1/skills/myorg/test-skill/latest-version").mock(
            return_value=httpx.Response(200, json={"version": "1.2.3", "checksum": "remote-checksum-no-match"})
        )
        respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={}))

        result = runner.invoke(
            app,
            ["publish", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert "1.2.4" in result.output
        assert "Published: myorg/test-skill@1.2.4" in result.output

    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_auto_bump_minor(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        tmp_path: Path,
    ) -> None:
        """Auto-bump minor: 1.2.3 -> 1.3.0."""
        _write_skill_md(tmp_path)

        respx.get("http://test:8000/v1/skills/myorg/test-skill/latest-version").mock(
            return_value=httpx.Response(200, json={"version": "1.2.3", "checksum": "remote-checksum-no-match"})
        )
        respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={}))

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--minor"],
        )

        assert result.exit_code == 0
        assert "1.3.0" in result.output
        assert "Published: myorg/test-skill@1.3.0" in result.output

    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_auto_bump_major(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        tmp_path: Path,
    ) -> None:
        """Auto-bump major: 1.2.3 -> 2.0.0."""
        _write_skill_md(tmp_path)

        respx.get("http://test:8000/v1/skills/myorg/test-skill/latest-version").mock(
            return_value=httpx.Response(200, json={"version": "1.2.3", "checksum": "remote-checksum-no-match"})
        )
        respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={}))

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--major"],
        )

        assert result.exit_code == 0
        assert "2.0.0" in result.output
        assert "Published: myorg/test-skill@2.0.0" in result.output

    def test_publish_no_skills_found(self, tmp_path: Path) -> None:
        """Publish should fail when no SKILL.md exists under the path."""
        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--version", "1.0.0"],
        )

        assert result.exit_code == 1
        assert "No skills found" in result.output

    def test_publish_invalid_semver(self, tmp_path: Path) -> None:
        """Publish should fail with an invalid semver string."""
        _write_skill_md(tmp_path)

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--version", "not-a-version"],
        )

        assert result.exit_code != 0

    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_409_conflict(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        tmp_path: Path,
    ) -> None:
        _write_skill_md(tmp_path)
        respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(409))

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--version", "1.0.0"],
        )

        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_publish_multiple_bump_flags_rejected(self, tmp_path: Path) -> None:
        """Specifying multiple bump flags should fail."""
        _write_skill_md(tmp_path)

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--minor", "--major"],
        )

        assert result.exit_code == 1
        assert "Only one" in result.output

    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_skips_when_unchanged(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        tmp_path: Path,
    ) -> None:
        """Auto-bump should skip publish when local checksum matches remote."""
        _write_skill_md(tmp_path)

        # Compute the checksum of the zip that _create_zip will produce
        from dhub.cli.registry import _create_zip
        from dhub.core.install import compute_checksum

        zip_data = _create_zip(tmp_path)
        local_checksum = compute_checksum(zip_data)

        respx.get("http://test:8000/v1/skills/myorg/test-skill/latest-version").mock(
            return_value=httpx.Response(200, json={"version": "1.0.0", "checksum": local_checksum})
        )
        publish_route = respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={}))

        result = runner.invoke(
            app,
            ["publish", str(tmp_path)],
        )

        assert result.exit_code == 0
        assert "No changes detected" in result.output
        assert "1.0.0" in result.output
        assert not publish_route.called


# ---------------------------------------------------------------------------
# install_command
# ---------------------------------------------------------------------------


class TestInstallCommand:
    @respx.mock
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_install_success(
        self,
        _mock_url,
        _mock_token,
        mock_skill_path,
        mock_checksum,
        tmp_path: Path,
    ) -> None:
        skill_dir = tmp_path / "myorg" / "my-skill"
        mock_skill_path.return_value = skill_dir

        zip_bytes = _make_zip_bytes()

        respx.get("http://test:8000/v1/resolve/myorg/my-skill").mock(
            return_value=httpx.Response(
                200,
                json={
                    "version": "1.0.0",
                    "download_url": "http://test:8000/download/skill.zip",
                    "checksum": "abc123",
                },
            )
        )
        respx.get("http://test:8000/download/skill.zip").mock(return_value=httpx.Response(200, content=zip_bytes))

        result = runner.invoke(app, ["install", "myorg/my-skill"])

        assert result.exit_code == 0
        assert "Installed myorg/my-skill@1.0.0" in result.output
        mock_checksum.assert_called_once_with(zip_bytes, "abc123")
        assert skill_dir.exists()

    @respx.mock
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_install_with_allow_risky_flag(
        self,
        _mock_url,
        _mock_token,
        mock_skill_path,
        mock_checksum,
        tmp_path: Path,
    ) -> None:
        """--allow-risky flag passes allow_risky=true to resolve request."""
        skill_dir = tmp_path / "myorg" / "my-skill"
        mock_skill_path.return_value = skill_dir

        zip_bytes = _make_zip_bytes()

        resolve_route = respx.get("http://test:8000/v1/resolve/myorg/my-skill").mock(
            return_value=httpx.Response(
                200,
                json={
                    "version": "1.0.0",
                    "download_url": "http://test:8000/download/skill.zip",
                    "checksum": "abc123",
                },
            )
        )
        respx.get("http://test:8000/download/skill.zip").mock(return_value=httpx.Response(200, content=zip_bytes))

        result = runner.invoke(app, ["install", "myorg/my-skill", "--allow-risky"])

        assert result.exit_code == 0
        # Verify allow_risky was passed in the resolve request params
        request = resolve_route.calls.last.request
        assert "allow_risky=true" in str(request.url)

    def test_install_invalid_skill_ref(self) -> None:
        """Install should reject a skill reference without a slash."""
        result = runner.invoke(app, ["install", "no-slash"])

        assert result.exit_code == 1
        assert "org/skill format" in result.output

    @respx.mock
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_install_404_not_found(
        self,
        _mock_url,
        _mock_token,
        mock_skill_path,
        tmp_path: Path,
    ) -> None:
        mock_skill_path.return_value = tmp_path / "org" / "skill"
        respx.get("http://test:8000/v1/resolve/org/skill").mock(return_value=httpx.Response(404))

        result = runner.invoke(app, ["install", "org/skill"])

        assert result.exit_code == 1
        assert "not found" in result.output

    @respx.mock
    @patch("dhub.core.install.link_skill_to_agent", return_value=Path("/mock/link"))
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_install_with_agent_flag(
        self,
        _mock_url,
        _mock_token,
        mock_skill_path,
        mock_checksum,
        mock_link,
        tmp_path: Path,
    ) -> None:
        skill_dir = tmp_path / "myorg" / "my-skill"
        mock_skill_path.return_value = skill_dir
        zip_bytes = _make_zip_bytes()

        respx.get("http://test:8000/v1/resolve/myorg/my-skill").mock(
            return_value=httpx.Response(
                200,
                json={
                    "version": "2.0.0",
                    "download_url": "http://test:8000/download/skill.zip",
                    "checksum": "def456",
                },
            )
        )
        respx.get("http://test:8000/download/skill.zip").mock(return_value=httpx.Response(200, content=zip_bytes))

        result = runner.invoke(app, ["install", "myorg/my-skill", "--agent", "claude"])

        assert result.exit_code == 0
        mock_link.assert_called_once_with("myorg", "my-skill", "claude")
        assert "Linked to claude" in result.output

    @respx.mock
    @patch("dhub.core.install.link_skill_to_all_agents", return_value=["claude", "cursor"])
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_install_with_agent_all(
        self,
        _mock_url,
        _mock_token,
        mock_skill_path,
        mock_checksum,
        mock_link_all,
        tmp_path: Path,
    ) -> None:
        skill_dir = tmp_path / "myorg" / "my-skill"
        mock_skill_path.return_value = skill_dir
        zip_bytes = _make_zip_bytes()

        respx.get("http://test:8000/v1/resolve/myorg/my-skill").mock(
            return_value=httpx.Response(
                200,
                json={
                    "version": "3.0.0",
                    "download_url": "http://test:8000/download/skill.zip",
                    "checksum": "ghi789",
                },
            )
        )
        respx.get("http://test:8000/download/skill.zip").mock(return_value=httpx.Response(200, content=zip_bytes))

        result = runner.invoke(app, ["install", "myorg/my-skill", "--agent", "all"])

        assert result.exit_code == 0
        mock_link_all.assert_called_once_with("myorg", "my-skill")
        assert "claude" in result.output
        assert "cursor" in result.output


# ---------------------------------------------------------------------------
# list_command
# ---------------------------------------------------------------------------


class TestListCommand:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_command(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """List displays a table when skills exist."""
        respx.get("http://test:8000/v1/skills").mock(
            return_value=httpx.Response(200, json={
                "items": [
                    {
                        "org_slug": "acme",
                        "skill_name": "doc-writer",
                        "description": "Writes docs",
                        "latest_version": "1.0.0",
                        "updated_at": "2025-06-01",
                        "safety_rating": "A",
                        "author": "alice",
                        "download_count": 5,
                    },
                ],
                "total": 1,
                "page": 1,
                "page_size": 20,
                "total_pages": 1,
            })
        )
        respx.get("http://test:8000/cli/latest-version").mock(
            return_value=httpx.Response(200, json={"latest_version": ""})
        )

        result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "Registry:" in result.output
        assert "http://test:8000" in result.output
        assert "acme" in result.output
        assert "1.0.0" in result.output
        assert "alice" in result.output
        assert "5" in result.output
        assert "Page 1 of 1" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_command_empty(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """List prints a message when no skills are published."""
        respx.get("http://test:8000/v1/skills").mock(
            return_value=httpx.Response(200, json={
                "items": [],
                "total": 0,
                "page": 1,
                "page_size": 20,
                "total_pages": 1,
            })
        )
        respx.get("http://test:8000/cli/latest-version").mock(
            return_value=httpx.Response(200, json={"latest_version": ""})
        )

        result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "Registry:" in result.output
        assert "No skills published yet" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_command_with_page_option(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """--page and --page-size flags are sent as query params."""
        route = respx.get("http://test:8000/v1/skills").mock(
            return_value=httpx.Response(200, json={
                "items": [],
                "total": 50,
                "page": 3,
                "page_size": 5,
                "total_pages": 10,
            })
        )
        respx.get("http://test:8000/cli/latest-version").mock(
            return_value=httpx.Response(200, json={"latest_version": ""})
        )

        result = runner.invoke(app, ["list", "--page", "3", "--page-size", "5"])

        assert result.exit_code == 0
        request = route.calls.last.request
        assert "page=3" in str(request.url)
        assert "page_size=5" in str(request.url)


# ---------------------------------------------------------------------------
# delete_command
# ---------------------------------------------------------------------------


class TestDeleteCommand:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_delete_single_version_success(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.delete("http://test:8000/v1/skills/myorg/my-skill/1.0.0").mock(return_value=httpx.Response(200, json={}))

        result = runner.invoke(app, ["delete", "myorg/my-skill", "--version", "1.0.0"])

        assert result.exit_code == 0
        assert "Deleted: myorg/my-skill@1.0.0" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_delete_all_versions_success(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Delete without --version should prompt confirmation and delete all."""
        respx.delete("http://test:8000/v1/skills/myorg/my-skill").mock(
            return_value=httpx.Response(
                200,
                json={
                    "org_slug": "myorg",
                    "skill_name": "my-skill",
                    "versions_deleted": 3,
                },
            )
        )

        # 'y' confirms the prompt
        result = runner.invoke(app, ["delete", "myorg/my-skill"], input="y\n")

        assert result.exit_code == 0
        assert "3 version(s)" in result.output

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_delete_all_versions_aborted(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Delete all should abort if user declines confirmation."""
        result = runner.invoke(app, ["delete", "myorg/my-skill"], input="n\n")

        assert result.exit_code == 1

    def test_delete_invalid_skill_ref(self) -> None:
        """Delete should reject a skill reference without a slash."""
        result = runner.invoke(app, ["delete", "no-slash", "--version", "1.0.0"])

        assert result.exit_code == 1
        assert "org/skill format" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_delete_404_not_found(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.delete("http://test:8000/v1/skills/myorg/my-skill/9.9.9").mock(return_value=httpx.Response(404))

        result = runner.invoke(app, ["delete", "myorg/my-skill", "--version", "9.9.9"])

        assert result.exit_code == 1
        assert "not found" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_delete_403_forbidden(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.delete("http://test:8000/v1/skills/myorg/my-skill/1.0.0").mock(return_value=httpx.Response(403))

        result = runner.invoke(app, ["delete", "myorg/my-skill", "--version", "1.0.0"])

        assert result.exit_code == 1
        assert "permission" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_delete_all_404_not_found(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Delete all for a non-existent skill should return error."""
        respx.delete("http://test:8000/v1/skills/myorg/no-skill").mock(return_value=httpx.Response(404))

        result = runner.invoke(app, ["delete", "myorg/no-skill"], input="y\n")

        assert result.exit_code == 1
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# publish --private
# ---------------------------------------------------------------------------

class TestPublishPrivate:

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_private_sends_visibility_org(
        self,
        _mock_url,
        _mock_token,
        tmp_path: Path,
    ) -> None:
        """--private flag should include visibility=org in the metadata."""
        _write_skill_md(tmp_path)
        publish_route = respx.post("http://test:8000/v1/publish").mock(
            return_value=httpx.Response(200, json={})
        )

        result = runner.invoke(
            app,
            ["publish", "myorg/my-skill", str(tmp_path), "--version", "1.0.0", "--private"],
        )

        assert result.exit_code == 0
        assert "Published: myorg/my-skill@1.0.0" in result.output
        assert "org-private" in result.output

        # Verify the metadata sent to the server contains visibility=org
        request = publish_route.calls.last.request
        body = request.content.decode("utf-8", errors="replace")
        assert '"visibility": "org"' in body

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_default_is_public(
        self,
        _mock_url,
        _mock_token,
        tmp_path: Path,
    ) -> None:
        """Without --private, visibility should default to public."""
        _write_skill_md(tmp_path)
        publish_route = respx.post("http://test:8000/v1/publish").mock(
            return_value=httpx.Response(200, json={})
        )

        result = runner.invoke(
            app,
            ["publish", "myorg/my-skill", str(tmp_path), "--version", "1.0.0"],
        )

        assert result.exit_code == 0
        request = publish_route.calls.last.request
        body = request.content.decode("utf-8", errors="replace")
        assert '"visibility": "public"' in body


# ---------------------------------------------------------------------------
# visibility_command
# ---------------------------------------------------------------------------

class TestVisibilityCommand:

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_visibility_change_success(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Changing visibility should succeed."""
        respx.put("http://test:8000/v1/skills/myorg/my-skill/visibility").mock(
            return_value=httpx.Response(200, json={
                "org_slug": "myorg",
                "skill_name": "my-skill",
                "visibility": "org",
            })
        )

        result = runner.invoke(app, ["visibility", "myorg/my-skill", "org"])

        assert result.exit_code == 0
        assert "org-private" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_visibility_change_to_public(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Changing visibility to public."""
        respx.put("http://test:8000/v1/skills/myorg/my-skill/visibility").mock(
            return_value=httpx.Response(200, json={
                "org_slug": "myorg",
                "skill_name": "my-skill",
                "visibility": "public",
            })
        )

        result = runner.invoke(app, ["visibility", "myorg/my-skill", "public"])

        assert result.exit_code == 0
        assert "public" in result.output

    def test_visibility_invalid_ref(self) -> None:
        """Visibility with bad skill ref should fail."""
        result = runner.invoke(app, ["visibility", "no-slash", "org"])

        assert result.exit_code == 1
        assert "org/skill format" in result.output

    def test_visibility_invalid_value(self) -> None:
        """Invalid visibility value should fail."""
        result = runner.invoke(app, ["visibility", "myorg/my-skill", "invalid"])

        assert result.exit_code == 1
        assert "public" in result.output or "org" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_visibility_403_forbidden(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Non-admin should get permission error."""
        respx.put("http://test:8000/v1/skills/myorg/my-skill/visibility").mock(
            return_value=httpx.Response(403)
        )

        result = runner.invoke(app, ["visibility", "myorg/my-skill", "org"])

        assert result.exit_code == 1
        assert "admin" in result.output.lower()

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_visibility_404_not_found(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Non-existent skill should return error."""
        respx.put("http://test:8000/v1/skills/myorg/no-skill/visibility").mock(
            return_value=httpx.Response(404)
        )

        result = runner.invoke(app, ["visibility", "myorg/no-skill", "org"])

        assert result.exit_code == 1
        assert "not found" in result.output


# ---------------------------------------------------------------------------
# access grant/revoke/list
# ---------------------------------------------------------------------------

class TestAccessGrant:

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_access_grant_success(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Grant access should succeed."""
        respx.post("http://test:8000/v1/skills/myorg/my-skill/access").mock(
            return_value=httpx.Response(201, json={
                "org_slug": "myorg",
                "skill_name": "my-skill",
                "grantee_org_slug": "other-org",
            })
        )

        result = runner.invoke(app, ["access", "grant", "myorg/my-skill", "other-org"])

        assert result.exit_code == 0
        assert "Granted access" in result.output
        assert "other-org" in result.output

    def test_access_grant_invalid_ref(self) -> None:
        """Grant with invalid skill ref should fail."""
        result = runner.invoke(app, ["access", "grant", "no-slash", "other-org"])

        assert result.exit_code == 1
        assert "org/skill format" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_access_grant_404(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Grant to non-existent skill or org should show error."""
        respx.post("http://test:8000/v1/skills/myorg/my-skill/access").mock(
            return_value=httpx.Response(404, json={"detail": "Skill 'my-skill' not found"})
        )

        result = runner.invoke(app, ["access", "grant", "myorg/my-skill", "other-org"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_access_grant_403(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Non-admin should get permission error."""
        respx.post("http://test:8000/v1/skills/myorg/my-skill/access").mock(
            return_value=httpx.Response(403)
        )

        result = runner.invoke(app, ["access", "grant", "myorg/my-skill", "other-org"])

        assert result.exit_code == 1
        assert "admin" in result.output.lower()

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_access_grant_409_duplicate(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Duplicate grant should show already-granted message."""
        respx.post("http://test:8000/v1/skills/myorg/my-skill/access").mock(
            return_value=httpx.Response(409)
        )

        result = runner.invoke(app, ["access", "grant", "myorg/my-skill", "other-org"])

        assert result.exit_code == 1
        assert "already granted" in result.output.lower()


class TestAccessRevoke:

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_access_revoke_success(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Revoke access should succeed."""
        respx.delete("http://test:8000/v1/skills/myorg/my-skill/access/other-org").mock(
            return_value=httpx.Response(200, json={
                "org_slug": "myorg",
                "skill_name": "my-skill",
                "grantee_org_slug": "other-org",
            })
        )

        result = runner.invoke(app, ["access", "revoke", "myorg/my-skill", "other-org"])

        assert result.exit_code == 0
        assert "Revoked access" in result.output
        assert "other-org" in result.output

    def test_access_revoke_invalid_ref(self) -> None:
        """Revoke with invalid skill ref should fail."""
        result = runner.invoke(app, ["access", "revoke", "no-slash", "other-org"])

        assert result.exit_code == 1
        assert "org/skill format" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_access_revoke_404(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Revoking a non-existent grant should show error."""
        respx.delete("http://test:8000/v1/skills/myorg/my-skill/access/other-org").mock(
            return_value=httpx.Response(404, json={"detail": "No access grant found"})
        )

        result = runner.invoke(app, ["access", "revoke", "myorg/my-skill", "other-org"])

        assert result.exit_code == 1


class TestAccessList:

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_access_list_success(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """List access grants should display a table."""
        respx.get("http://test:8000/v1/skills/myorg/my-skill/access").mock(
            return_value=httpx.Response(200, json=[
                {
                    "grantee_org_slug": "partner-org",
                    "granted_by": "admin-user",
                    "created_at": "2025-06-01T12:00:00",
                },
            ])
        )

        result = runner.invoke(app, ["access", "list", "myorg/my-skill"])

        assert result.exit_code == 0
        assert "partner-org" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_access_list_empty(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """List with no grants should show a message."""
        respx.get("http://test:8000/v1/skills/myorg/my-skill/access").mock(
            return_value=httpx.Response(200, json=[])
        )

        result = runner.invoke(app, ["access", "list", "myorg/my-skill"])

        assert result.exit_code == 0
        assert "No access grants" in result.output

    def test_access_list_invalid_ref(self) -> None:
        """List with invalid skill ref should fail."""
        result = runner.invoke(app, ["access", "list", "no-slash"])

        assert result.exit_code == 1
        assert "org/skill format" in result.output
