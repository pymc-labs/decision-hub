"""Tests for dhub install --repo flag."""

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


def _make_zip_bytes() -> bytes:
    """Create a small in-memory zip archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\nname: s\ndescription: d\n---\nbody\n")
    return buf.getvalue()


def _repo_response(items: list[dict], repo_url: str = "https://github.com/acme/repo") -> dict:
    """Build a by-repo response envelope."""
    return {"items": items, "total": len(items), "repo_url": repo_url}


# ---------------------------------------------------------------------------
# install --repo
# ---------------------------------------------------------------------------


class TestInstallRepo:
    @respx.mock
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_install_repo_installs_all_skills(
        self,
        _mock_url,
        _mock_token,
        mock_skill_path,
        mock_checksum,
        tmp_path: Path,
    ) -> None:
        """--repo queries by-repo endpoint and installs each skill."""
        mock_skill_path.side_effect = lambda org, name: tmp_path / org / name

        zip_bytes = _make_zip_bytes()

        items = [
            {"org_slug": "acme", "skill_name": "skill-a", "latest_version": "1.0.0"},
            {"org_slug": "acme", "skill_name": "skill-b", "latest_version": "2.0.0"},
        ]
        respx.get("http://test:8000/v1/skills/by-repo").mock(
            return_value=httpx.Response(200, json=_repo_response(items))
        )
        respx.get("http://test:8000/v1/resolve/acme/skill-a").mock(
            return_value=httpx.Response(
                200,
                json={"version": "1.0.0", "download_url": "http://test:8000/dl/a.zip", "checksum": "abc"},
            )
        )
        respx.get("http://test:8000/v1/resolve/acme/skill-b").mock(
            return_value=httpx.Response(
                200,
                json={"version": "2.0.0", "download_url": "http://test:8000/dl/b.zip", "checksum": "def"},
            )
        )
        respx.get("http://test:8000/dl/a.zip").mock(return_value=httpx.Response(200, content=zip_bytes))
        respx.get("http://test:8000/dl/b.zip").mock(return_value=httpx.Response(200, content=zip_bytes))

        result = runner.invoke(app, ["install", "--repo", "acme/repo"])

        assert result.exit_code == 0
        assert "Found 2 skills" in result.output
        assert "Installed 2/2" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_install_repo_no_skills_found(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """--repo with unknown repo shows error."""
        respx.get("http://test:8000/v1/skills/by-repo").mock(
            return_value=httpx.Response(
                200,
                json=_repo_response([], repo_url="https://github.com/no/such"),
            )
        )

        result = runner.invoke(app, ["install", "--repo", "no/such"])

        assert result.exit_code == 1
        assert "No published skills found" in result.output

    def test_install_mutual_exclusion(self) -> None:
        """Cannot pass both skill_ref and --repo."""
        result = runner.invoke(app, ["install", "acme/skill", "--repo", "acme/repo"])

        assert result.exit_code == 1
        assert "Cannot use both" in result.output

    def test_install_neither_ref_nor_repo(self) -> None:
        """Must provide either a skill reference or --repo."""
        result = runner.invoke(app, ["install"])

        assert result.exit_code == 1
        assert "Provide a skill reference" in result.output

    def test_install_repo_url_too_long(self) -> None:
        """--repo with a URL exceeding 500 chars is rejected client-side."""
        long_repo = "a" * 501
        result = runner.invoke(app, ["install", "--repo", long_repo])

        assert result.exit_code == 1
        assert "too long" in result.output

    @respx.mock
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_install_repo_accepts_full_url(
        self,
        _mock_url,
        _mock_token,
        mock_skill_path,
        mock_checksum,
        tmp_path: Path,
    ) -> None:
        """--repo accepts full GitHub URL."""
        mock_skill_path.side_effect = lambda org, name: tmp_path / org / name
        zip_bytes = _make_zip_bytes()

        items = [{"org_slug": "acme", "skill_name": "skill-a", "latest_version": "1.0.0"}]
        by_repo_route = respx.get("http://test:8000/v1/skills/by-repo").mock(
            return_value=httpx.Response(200, json=_repo_response(items))
        )
        respx.get("http://test:8000/v1/resolve/acme/skill-a").mock(
            return_value=httpx.Response(
                200,
                json={"version": "1.0.0", "download_url": "http://test:8000/dl/a.zip", "checksum": "abc"},
            )
        )
        respx.get("http://test:8000/dl/a.zip").mock(return_value=httpx.Response(200, content=zip_bytes))

        result = runner.invoke(app, ["install", "--repo", "https://github.com/acme/repo"])

        assert result.exit_code == 0
        # Verify the full URL was passed through to the endpoint
        request = by_repo_route.calls[0].request
        assert request.url.params["repo_url"] == "https://github.com/acme/repo"

    @respx.mock
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_install_repo_accepts_owner_repo_shorthand(
        self,
        _mock_url,
        _mock_token,
        mock_skill_path,
        mock_checksum,
        tmp_path: Path,
    ) -> None:
        """--repo accepts owner/repo shorthand, expanding to full GitHub URL."""
        mock_skill_path.side_effect = lambda org, name: tmp_path / org / name
        zip_bytes = _make_zip_bytes()

        items = [{"org_slug": "acme", "skill_name": "skill-a", "latest_version": "1.0.0"}]
        by_repo_route = respx.get("http://test:8000/v1/skills/by-repo").mock(
            return_value=httpx.Response(200, json=_repo_response(items))
        )
        respx.get("http://test:8000/v1/resolve/acme/skill-a").mock(
            return_value=httpx.Response(
                200,
                json={"version": "1.0.0", "download_url": "http://test:8000/dl/a.zip", "checksum": "abc"},
            )
        )
        respx.get("http://test:8000/dl/a.zip").mock(return_value=httpx.Response(200, content=zip_bytes))

        result = runner.invoke(app, ["install", "--repo", "acme/repo"])

        assert result.exit_code == 0
        # Verify owner/repo was expanded to full GitHub URL
        request = by_repo_route.calls[0].request
        assert request.url.params["repo_url"] == "https://github.com/acme/repo"

    @respx.mock
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_install_repo_continues_on_single_failure(
        self,
        _mock_url,
        _mock_token,
        mock_skill_path,
        mock_checksum,
        tmp_path: Path,
    ) -> None:
        """If one skill fails, others are still installed."""
        mock_skill_path.side_effect = lambda org, name: tmp_path / org / name
        zip_bytes = _make_zip_bytes()

        items = [
            {"org_slug": "acme", "skill_name": "good-skill", "latest_version": "1.0.0"},
            {"org_slug": "acme", "skill_name": "bad-skill", "latest_version": "1.0.0"},
        ]
        respx.get("http://test:8000/v1/skills/by-repo").mock(
            return_value=httpx.Response(200, json=_repo_response(items))
        )
        respx.get("http://test:8000/v1/resolve/acme/good-skill").mock(
            return_value=httpx.Response(
                200,
                json={"version": "1.0.0", "download_url": "http://test:8000/dl/good.zip", "checksum": "abc"},
            )
        )
        # bad-skill returns 404
        respx.get("http://test:8000/v1/resolve/acme/bad-skill").mock(return_value=httpx.Response(404))
        respx.get("http://test:8000/dl/good.zip").mock(return_value=httpx.Response(200, content=zip_bytes))

        result = runner.invoke(app, ["install", "--repo", "acme/repo"])

        assert result.exit_code == 0
        assert "Installed 1/2" in result.output
        assert "1 skills failed" in result.output
