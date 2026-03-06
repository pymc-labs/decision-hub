"""Tests for dhub.cli.registry -- publish, install, list, and delete commands."""

import io
import json
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

    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_without_private_omits_visibility(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        tmp_path: Path,
    ) -> None:
        """Publish without --private should NOT include visibility in metadata."""
        _write_skill_md(tmp_path)
        publish_route = respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={}))

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--version", "1.0.0"],
        )

        assert result.exit_code == 0
        # Extract the metadata from the request
        request = publish_route.calls[0].request
        # multipart form data: extract metadata field
        body = request.content.decode("utf-8", errors="replace")
        # Find the JSON metadata in the multipart body
        for part in body.split("Content-Disposition"):
            if 'name="metadata"' in part:
                # The JSON is after the blank line
                json_str = part.split("\r\n\r\n", 1)[1].split("\r\n--", 1)[0]
                meta = json.loads(json_str)
                assert "visibility" not in meta
                break
        else:
            raise AssertionError("metadata field not found in request")

    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_with_private_includes_org_visibility(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        tmp_path: Path,
    ) -> None:
        """Publish with --private should include visibility='org' in metadata."""
        _write_skill_md(tmp_path)
        publish_route = respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={}))

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--version", "1.0.0", "--private"],
        )

        assert result.exit_code == 0
        request = publish_route.calls[0].request
        body = request.content.decode("utf-8", errors="replace")
        for part in body.split("Content-Disposition"):
            if 'name="metadata"' in part:
                json_str = part.split("\r\n\r\n", 1)[1].split("\r\n--", 1)[0]
                meta = json.loads(json_str)
                assert meta["visibility"] == "org"
                break
        else:
            raise AssertionError("metadata field not found in request")

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_with_org_flag_skips_auto_detect(
        self,
        _mock_url,
        _mock_token,
        tmp_path: Path,
    ) -> None:
        """--org overrides auto-detection and uses the specified org."""
        _write_skill_md(tmp_path)
        publish_route = respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={}))

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--version", "1.0.0", "--org", "custom-org"],
        )

        assert result.exit_code == 0
        assert "Using namespace: custom-org" in result.output
        assert "Published: custom-org/test-skill@1.0.0" in result.output
        # Verify the org in metadata
        request = publish_route.calls[0].request
        body = request.content.decode("utf-8", errors="replace")
        for part in body.split("Content-Disposition"):
            if 'name="metadata"' in part:
                json_str = part.split("\r\n\r\n", 1)[1].split("\r\n--", 1)[0]
                meta = json.loads(json_str)
                assert meta["org_slug"] == "custom-org"
                break
        else:
            raise AssertionError("metadata field not found in request")

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_with_org_short_flag(
        self,
        _mock_url,
        _mock_token,
        tmp_path: Path,
    ) -> None:
        """Short -o flag works as an alias for --org."""
        _write_skill_md(tmp_path)
        respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={}))

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--version", "1.0.0", "-o", "short-org"],
        )

        assert result.exit_code == 0
        assert "Published: short-org/test-skill@1.0.0" in result.output


# ---------------------------------------------------------------------------
# install_command
# ---------------------------------------------------------------------------


class TestInstallCommand:
    @respx.mock
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
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
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
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
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
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
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
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
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_install_rejects_zip_slip(
        self,
        _mock_url,
        _mock_token,
        mock_skill_path,
        mock_checksum,
        tmp_path: Path,
    ) -> None:
        """Install should reject a zip with path-traversal entries."""
        skill_dir = tmp_path / "myorg" / "my-skill"
        mock_skill_path.return_value = skill_dir

        # Create a malicious zip with a path-traversal entry
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../.bashrc", b"malicious")
        malicious_zip = buf.getvalue()

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
        respx.get("http://test:8000/download/skill.zip").mock(return_value=httpx.Response(200, content=malicious_zip))

        result = runner.invoke(app, ["install", "myorg/my-skill"])

        assert result.exit_code == 1
        assert "escapes target directory" in result.output

    @respx.mock
    @patch("dhub.core.install.link_skill_to_all_agents", return_value=["claude", "cursor"])
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
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


def _paginated_response(
    items: list[dict],
    total: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Helper to build a paginated skills response envelope."""
    import math

    if total is None:
        total = len(items)
    total_pages = math.ceil(total / page_size) if total > 0 else 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


class TestListCommand:
    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_command(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """List displays a table when skills exist."""
        skills = [
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
        ]
        respx.get("http://test:8000/v1/skills").mock(return_value=httpx.Response(200, json=_paginated_response(skills)))
        respx.get("http://test:8000/cli/latest-version").mock(
            return_value=httpx.Response(200, json={"latest_version": ""})
        )

        result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "Registry:" in result.output
        assert "http://test:8000" in result.output
        assert "Author" in result.output
        assert "Downl" in result.output
        assert "acme" in result.output
        assert "doc-w" in result.output
        assert "1.0.0" in result.output
        assert "alice" in result.output
        assert "5" in result.output
        assert "Page 1 of 1" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_command_empty(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """List prints a message when no skills are published."""
        respx.get("http://test:8000/v1/skills").mock(return_value=httpx.Response(200, json=_paginated_response([])))
        respx.get("http://test:8000/cli/latest-version").mock(
            return_value=httpx.Response(200, json={"latest_version": ""})
        )

        result = runner.invoke(app, ["list"])

        assert result.exit_code == 0
        assert "Registry:" in result.output
        assert "No skills found" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_filter_by_org(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """--org passes org filter as server-side query param."""
        acme_skills = [
            {
                "org_slug": "acme",
                "skill_name": "skill-a",
                "description": "First",
                "latest_version": "1.0.0",
                "updated_at": "2025-06-01",
                "safety_rating": "A",
                "author": "alice",
                "download_count": 5,
            },
        ]
        # Server returns only acme skills when org=acme is passed
        route = respx.get("http://test:8000/v1/skills").mock(
            return_value=httpx.Response(200, json=_paginated_response(acme_skills))
        )
        respx.get("http://test:8000/cli/latest-version").mock(
            return_value=httpx.Response(200, json={"latest_version": ""})
        )

        result = runner.invoke(app, ["list", "--org", "acme"])

        assert result.exit_code == 0
        assert "acme" in result.output
        assert "alice" in result.output
        # Verify the org param was sent to the server
        assert route.called
        assert route.calls[0].request.url.params["org"] == "acme"

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_filter_by_skill(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """--skill passes search filter as server-side query param."""
        matching_skills = [
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
        ]
        # Server returns only matching skills when search=doc is passed
        route = respx.get("http://test:8000/v1/skills").mock(
            return_value=httpx.Response(200, json=_paginated_response(matching_skills))
        )
        respx.get("http://test:8000/cli/latest-version").mock(
            return_value=httpx.Response(200, json={"latest_version": ""})
        )

        result = runner.invoke(app, ["list", "--skill", "doc"])

        assert result.exit_code == 0
        assert "alice" in result.output
        # Verify the search param was sent to the server
        assert route.called
        assert route.calls[0].request.url.params["search"] == "doc"

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_filter_no_matches(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Filtering with no matches shows a descriptive message."""
        # Server returns empty when org=nonexistent
        route = respx.get("http://test:8000/v1/skills").mock(
            return_value=httpx.Response(200, json=_paginated_response([]))
        )
        respx.get("http://test:8000/cli/latest-version").mock(
            return_value=httpx.Response(200, json={"latest_version": ""})
        )

        result = runner.invoke(app, ["list", "--org", "nonexistent"])

        assert result.exit_code == 0
        assert "No skills found" in result.output
        # Verify the org param was sent to the server
        assert route.called
        assert route.calls[0].request.url.params["org"] == "nonexistent"

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_all_pages(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """--all fetches all pages without prompting."""
        page1_skills = [
            {
                "org_slug": "acme",
                "skill_name": "skill-a",
                "description": "First",
                "latest_version": "1.0.0",
                "updated_at": "2025-06-01",
                "safety_rating": "A",
                "author": "alice",
                "download_count": 5,
            },
        ]
        page2_skills = [
            {
                "org_slug": "acme",
                "skill_name": "skill-b",
                "description": "Second",
                "latest_version": "2.0.0",
                "updated_at": "2025-06-01",
                "safety_rating": "B",
                "author": "bob",
                "download_count": 3,
            },
        ]
        responses = iter(
            [
                httpx.Response(
                    200,
                    json=_paginated_response(page1_skills, total=2, page=1, page_size=1),
                ),
                httpx.Response(
                    200,
                    json=_paginated_response(page2_skills, total=2, page=2, page_size=1),
                ),
            ]
        )
        respx.get("http://test:8000/v1/skills").mock(side_effect=lambda req: next(responses))
        respx.get("http://test:8000/cli/latest-version").mock(
            return_value=httpx.Response(200, json={"latest_version": ""})
        )

        result = runner.invoke(app, ["list", "--page-size", "1", "--all"])

        assert result.exit_code == 0
        assert "alice" in result.output
        assert "bob" in result.output
        assert "Page 1 of 2" in result.output
        assert "Page 2 of 2" in result.output


# ---------------------------------------------------------------------------
# list_command JSON output
# ---------------------------------------------------------------------------


class TestListJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_json_single_page(self, _mock_url, _mock_token) -> None:
        response = {
            "items": [
                {
                    "org_slug": "acme",
                    "skill_name": "test-skill",
                    "description": "A test",
                    "latest_version": "1.0.0",
                    "updated_at": "2026-01-01T00:00:00",
                    "safety_rating": "A",
                    "author": "alice",
                    "download_count": 42,
                    "category": "Testing",
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 50,
            "total_pages": 1,
        }
        respx.get("http://test:8000/v1/skills").mock(return_value=httpx.Response(200, json=response))
        result = runner.invoke(app, ["--output", "json", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["skill_name"] == "test-skill"

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_json_multi_page(self, _mock_url, _mock_token) -> None:
        page1 = {
            "items": [
                {
                    "org_slug": "a",
                    "skill_name": "s1",
                    "description": "",
                    "latest_version": "1.0.0",
                    "updated_at": "",
                    "safety_rating": "A",
                    "author": "",
                    "download_count": 0,
                    "category": "",
                }
            ],
            "total": 2,
            "page": 1,
            "page_size": 1,
            "total_pages": 2,
        }
        page2 = {
            "items": [
                {
                    "org_slug": "a",
                    "skill_name": "s2",
                    "description": "",
                    "latest_version": "1.0.0",
                    "updated_at": "",
                    "safety_rating": "A",
                    "author": "",
                    "download_count": 0,
                    "category": "",
                }
            ],
            "total": 2,
            "page": 2,
            "page_size": 1,
            "total_pages": 2,
        }
        route = respx.get("http://test:8000/v1/skills")
        route.side_effect = [httpx.Response(200, json=page1), httpx.Response(200, json=page2)]
        result = runner.invoke(app, ["--output", "json", "list", "--page-size", "1"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total"] == 2
        assert len(data["items"]) == 2


# ---------------------------------------------------------------------------
# publish tracking flags
# ---------------------------------------------------------------------------


class TestPublishTrackingFlags:
    def test_no_track_and_track_mutually_exclusive(self, tmp_path: Path) -> None:
        """--no-track and --track together should error."""
        _write_skill_md(tmp_path)

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--no-track", "--track"],
        )

        assert result.exit_code == 1
        assert "mutually exclusive" in result.output

    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_track_flag_only_for_git_urls(
        self,
        _mock_url,
        _mock_token,
        tmp_path: Path,
    ) -> None:
        """--track should error when used with a local directory."""
        _write_skill_md(tmp_path)

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--track", "--version", "1.0.0"],
        )

        assert result.exit_code == 1
        assert "--track" in result.output


# ---------------------------------------------------------------------------
# _ensure_tracker
# ---------------------------------------------------------------------------


class TestEnsureTracker:
    @respx.mock
    def test_creates_tracker_when_none_exists(self) -> None:
        """Should create a new tracker when no existing tracker matches."""
        from dhub.cli.registry import _ensure_tracker

        respx.get("http://test:8000/v1/trackers").mock(return_value=httpx.Response(200, json=[]))
        respx.post("http://test:8000/v1/trackers").mock(
            return_value=httpx.Response(
                201,
                json={"id": "abc", "warning": None},
            )
        )

        _ensure_tracker(
            "http://test:8000",
            {"Authorization": "Bearer tok"},
            "https://github.com/org/repo",
            "main",
        )

        assert respx.calls.call_count == 2
        create_call = respx.calls[1]
        body = json.loads(create_call.request.content)
        assert body["repo_url"] == "https://github.com/org/repo"
        assert body["branch"] == "main"

    @respx.mock
    def test_skips_create_when_tracker_exists_and_enabled(self) -> None:
        """Should do nothing when tracker exists and is enabled."""
        from dhub.cli.registry import _ensure_tracker

        respx.get("http://test:8000/v1/trackers").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "abc-123",
                        "repo_url": "https://github.com/org/repo",
                        "branch": "main",
                        "enabled": True,
                    }
                ],
            )
        )

        _ensure_tracker(
            "http://test:8000",
            {"Authorization": "Bearer tok"},
            "https://github.com/org/repo",
            "main",
        )

        # Only the GET call should have been made
        assert respx.calls.call_count == 1

    @respx.mock
    def test_reenables_paused_tracker_with_track_flag(self) -> None:
        """Should re-enable a paused tracker when --track is passed."""
        from dhub.cli.registry import _ensure_tracker

        respx.get("http://test:8000/v1/trackers").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "abc-123",
                        "repo_url": "https://github.com/org/repo",
                        "branch": "main",
                        "enabled": False,
                    }
                ],
            )
        )
        respx.patch("http://test:8000/v1/trackers/abc-123").mock(return_value=httpx.Response(200, json={}))

        _ensure_tracker(
            "http://test:8000",
            {"Authorization": "Bearer tok"},
            "https://github.com/org/repo",
            "main",
            track=True,
        )

        assert respx.calls.call_count == 2
        patch_call = respx.calls[1]
        body = json.loads(patch_call.request.content)
        assert body["enabled"] is True

    @respx.mock
    def test_paused_tracker_stays_paused_without_track_flag(self) -> None:
        """Should not re-enable a paused tracker without --track."""
        from dhub.cli.registry import _ensure_tracker

        respx.get("http://test:8000/v1/trackers").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": "abc-123",
                        "repo_url": "https://github.com/org/repo",
                        "branch": "main",
                        "enabled": False,
                    }
                ],
            )
        )

        _ensure_tracker(
            "http://test:8000",
            {"Authorization": "Bearer tok"},
            "https://github.com/org/repo",
            "main",
        )

        # Only the GET call — no PATCH to re-enable
        assert respx.calls.call_count == 1

    @respx.mock
    def test_shows_private_repo_warning(self, capsys) -> None:
        """Should display warning when tracker creation returns a warning."""
        from dhub.cli.registry import _ensure_tracker

        respx.get("http://test:8000/v1/trackers").mock(return_value=httpx.Response(200, json=[]))
        respx.post("http://test:8000/v1/trackers").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": "abc",
                    "warning": "This repo appears to be private. Add GITHUB_TOKEN.",
                },
            )
        )

        _ensure_tracker(
            "http://test:8000",
            {"Authorization": "Bearer tok"},
            "https://github.com/org/repo",
            "main",
        )

        assert respx.calls.call_count == 2

    @respx.mock
    def test_graceful_failure_on_api_error(self) -> None:
        """Should silently fail if the tracker API is unavailable."""
        from dhub.cli.registry import _ensure_tracker

        respx.get("http://test:8000/v1/trackers").mock(return_value=httpx.Response(500))

        # Should not raise
        _ensure_tracker(
            "http://test:8000",
            {"Authorization": "Bearer tok"},
            "https://github.com/org/repo",
            "main",
        )


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
# info_command JSON output
# ---------------------------------------------------------------------------


class TestInfoJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_info_json(self, _mock_url, _mock_token) -> None:
        summary = {
            "org_slug": "acme",
            "skill_name": "test-skill",
            "description": "A test",
            "latest_version": "1.0.0",
            "updated_at": "2026-01-01",
            "safety_rating": "A",
            "author": "alice",
            "download_count": 42,
            "category": "Testing",
            "visibility": "public",
        }
        respx.get("http://test:8000/v1/skills/acme/test-skill/summary").mock(
            return_value=httpx.Response(200, json=summary)
        )
        respx.get("http://test:8000/v1/skills/acme/test-skill/audit-log").mock(
            return_value=httpx.Response(
                200, json={"items": [], "total": 0, "page": 1, "page_size": 1, "total_pages": 0}
            )
        )
        respx.get("http://test:8000/v1/skills/acme/test-skill/eval-report").mock(
            return_value=httpx.Response(200, text="null", headers={"content-type": "application/json"})
        )
        result = runner.invoke(app, ["--output", "json", "info", "acme/test-skill"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["summary"]["skill_name"] == "test-skill"


# ---------------------------------------------------------------------------
# eval_report_command JSON output
# ---------------------------------------------------------------------------


class TestEvalReportJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_eval_report_json(self, _mock_url, _mock_token) -> None:
        report = {
            "id": "r1",
            "version_id": "v1",
            "agent": "claude",
            "judge_model": "claude-3",
            "case_results": [],
            "passed": 3,
            "total": 3,
            "total_duration_ms": 5000,
            "status": "completed",
            "error_message": None,
            "created_at": "2026-01-01",
        }
        respx.get("http://test:8000/v1/skills/acme/test-skill/versions/1.0.0/eval-report").mock(
            return_value=httpx.Response(200, json=report)
        )
        result = runner.invoke(app, ["--output", "json", "eval-report", "acme/test-skill@1.0.0"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["passed"] == 3


# ---------------------------------------------------------------------------
# publish JSON output
# ---------------------------------------------------------------------------


class TestPublishJsonOutput:
    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_json(self, _mock_url, _mock_token, _mock_org, tmp_path: Path) -> None:
        _write_skill_md(tmp_path)
        respx.get("http://test:8000/v1/skills/myorg/test-skill/latest-version").mock(return_value=httpx.Response(404))
        respx.post("http://test:8000/v1/publish").mock(
            return_value=httpx.Response(
                200,
                json={
                    "skill_id": "s1",
                    "version_id": "v1",
                    "version": "0.1.0",
                    "s3_key": "k",
                    "checksum": "abc",
                    "eval_status": "A",
                    "eval_run_id": "run-1",
                },
            )
        )
        result = runner.invoke(app, ["--output", "json", "publish", str(tmp_path)])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["org"] == "myorg"
        assert data["skill"] == "test-skill"
        assert data["version"] == "0.1.0"
        assert data["grade"] == "A"
        assert data["eval_run_id"] == "run-1"


# ---------------------------------------------------------------------------
# delete JSON output
# ---------------------------------------------------------------------------


class TestDeleteJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_delete_version_json(self, _mock_url, _mock_token) -> None:
        respx.delete("http://test:8000/v1/skills/acme/test-skill/1.0.0").mock(
            return_value=httpx.Response(200, json={"org_slug": "acme", "skill_name": "test-skill", "version": "1.0.0"})
        )
        result = runner.invoke(app, ["--output", "json", "delete", "acme/test-skill", "--version", "1.0.0"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["version"] == "1.0.0"
        assert data["org_slug"] == "acme"

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_delete_all_versions_json_skips_confirm(self, _mock_url, _mock_token) -> None:
        """JSON mode should skip the interactive confirmation prompt."""
        respx.delete("http://test:8000/v1/skills/acme/test-skill").mock(
            return_value=httpx.Response(
                200, json={"org_slug": "acme", "skill_name": "test-skill", "versions_deleted": 3}
            )
        )
        result = runner.invoke(app, ["--output", "json", "delete", "acme/test-skill"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["versions_deleted"] == 3


# ---------------------------------------------------------------------------
# visibility JSON output
# ---------------------------------------------------------------------------


class TestVisibilityJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_visibility_json(self, _mock_url, _mock_token) -> None:
        respx.put("http://test:8000/v1/skills/acme/test-skill/visibility").mock(
            return_value=httpx.Response(200, json={})
        )
        result = runner.invoke(app, ["--output", "json", "visibility", "acme/test-skill", "public"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["org"] == "acme"
        assert data["skill"] == "test-skill"
        assert data["visibility"] == "public"


# ---------------------------------------------------------------------------
# install JSON output
# ---------------------------------------------------------------------------


class TestInstallJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_install_json(self, _mock_url, _mock_token, tmp_path: Path) -> None:
        import hashlib

        # Build a valid zip with a SKILL.md
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: test-skill\ndescription: test\n---\nbody\n")
        zip_bytes = buf.getvalue()
        checksum = hashlib.sha256(zip_bytes).hexdigest()

        respx.get("http://test:8000/v1/resolve/acme/test-skill").mock(
            return_value=httpx.Response(
                200,
                json={"version": "1.0.0", "download_url": "http://test:8000/download/skill.zip", "checksum": checksum},
            )
        )
        respx.get("http://test:8000/download/skill.zip").mock(return_value=httpx.Response(200, content=zip_bytes))

        with patch("dhub.core.install.get_dhub_skill_path", return_value=tmp_path / "skills" / "acme" / "test-skill"):
            result = runner.invoke(app, ["--output", "json", "install", "acme/test-skill"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["org"] == "acme"
        assert data["skill"] == "test-skill"
        assert data["version"] == "1.0.0"
        assert "path" in data


# ---------------------------------------------------------------------------
# logs JSON output
# ---------------------------------------------------------------------------


class TestLogsJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_logs_list_json(self, _mock_url, _mock_token) -> None:
        runs = [
            {
                "id": "run-1",
                "status": "completed",
                "agent": "claude",
                "total_cases": 3,
                "current_case_index": 3,
                "stage": "done",
                "created_at": "2026-01-01T00:00:00",
            }
        ]
        respx.get("http://test:8000/v1/eval-runs").mock(return_value=httpx.Response(200, json=runs))
        result = runner.invoke(app, ["--output", "json", "logs"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["id"] == "run-1"

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_logs_show_run_status_json(self, _mock_url, _mock_token) -> None:
        run_id = "12345678-1234-1234-1234-123456789abc"
        run = {
            "id": run_id,
            "status": "completed",
            "agent": "claude",
            "total_cases": 2,
            "current_case_index": 2,
            "stage": "done",
            "created_at": "2026-01-01T00:00:00",
        }
        # The code first tries to resolve skill_ref as a UUID run ID
        respx.get(f"http://test:8000/v1/eval-runs/{run_id}").mock(return_value=httpx.Response(200, json=run))
        result = runner.invoke(app, ["--output", "json", "logs", run_id])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == run_id
        assert data["status"] == "completed"

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_logs_follow_ndjson(self, _mock_url, _mock_token) -> None:
        run_id = "12345678-1234-1234-1234-123456789abc"
        # Resolve the run ID
        respx.get(f"http://test:8000/v1/eval-runs/{run_id}").mock(return_value=httpx.Response(200, json={"id": run_id}))
        # Return two events then mark completed
        respx.get(f"http://test:8000/v1/eval-runs/{run_id}/logs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "events": [
                        {"type": "setup", "content": "Provisioning..."},
                        {"type": "case_start", "case_index": 0, "total_cases": 1, "case_name": "test-case"},
                    ],
                    "next_cursor": 2,
                    "run_status": "completed",
                },
            )
        )
        result = runner.invoke(app, ["--output", "json", "logs", run_id, "--follow"])
        assert result.exit_code == 0
        lines = [line for line in result.output.strip().split("\n") if line.strip()]
        assert len(lines) == 2
        event1 = json.loads(lines[0])
        assert event1["type"] == "setup"
        event2 = json.loads(lines[1])
        assert event2["type"] == "case_start"


# ---------------------------------------------------------------------------
# publish --dry-run
# ---------------------------------------------------------------------------


class TestPublishDryRun:
    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_dry_run_no_post(self, _mock_url, _mock_token, _mock_org, tmp_path: Path) -> None:
        """--dry-run should NOT call the publish endpoint."""
        _write_skill_md(tmp_path)
        respx.get("http://test:8000/v1/skills/myorg/test-skill/latest-version").mock(return_value=httpx.Response(404))
        # No POST mock — if publish is called, respx will raise

        result = runner.invoke(app, ["publish", str(tmp_path), "--dry-run"])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower() or "would publish" in result.output.lower()

    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_dry_run_json(self, _mock_url, _mock_token, _mock_org, tmp_path: Path) -> None:
        _write_skill_md(tmp_path)
        respx.get("http://test:8000/v1/skills/myorg/test-skill/latest-version").mock(return_value=httpx.Response(404))

        result = runner.invoke(app, ["--output", "json", "publish", str(tmp_path), "--dry-run"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["org"] == "myorg"
        assert data["skill"] == "test-skill"
        assert data["version"] == "0.1.0"
        assert "size_bytes" in data
        assert "files" in data


# ---------------------------------------------------------------------------
# delete --dry-run
# ---------------------------------------------------------------------------


class TestDeleteDryRun:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_dry_run_no_delete(self, _mock_url, _mock_token) -> None:
        """--dry-run should NOT call the delete endpoint."""
        respx.get("http://test:8000/v1/skills/acme/test-skill/summary").mock(
            return_value=httpx.Response(
                200, json={"org_slug": "acme", "skill_name": "test-skill", "latest_version": "1.0.0"}
            )
        )
        # No DELETE mock

        result = runner.invoke(app, ["delete", "acme/test-skill", "--version", "1.0.0", "--dry-run"])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower() or "would delete" in result.output.lower()

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_dry_run_json(self, _mock_url, _mock_token) -> None:
        respx.get("http://test:8000/v1/skills/acme/test-skill/summary").mock(
            return_value=httpx.Response(
                200, json={"org_slug": "acme", "skill_name": "test-skill", "latest_version": "1.0.0"}
            )
        )

        result = runner.invoke(
            app, ["--output", "json", "delete", "acme/test-skill", "--version", "1.0.0", "--dry-run"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["org"] == "acme"
        assert data["version"] == "1.0.0"
