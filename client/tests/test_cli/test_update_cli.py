"""Tests for dhub update command."""

import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx
import respx
from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


def _make_zip_bytes() -> bytes:
    """Create a small in-memory zip archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SKILL.md", "---\nname: s\ndescription: d\n---\nbody\n")
    return buf.getvalue()


class TestUpdateCommand:
    def test_update_no_args(self) -> None:
        """Update without args or --all should error."""
        result = runner.invoke(app, ["update"])
        assert result.exit_code == 1
        assert "Provide a skill reference or use --all" in result.output

    def test_update_both_ref_and_all(self) -> None:
        """Update with both a skill ref and --all should error."""
        result = runner.invoke(app, ["update", "myorg/my-skill", "--all"])
        assert result.exit_code == 1
        assert "Cannot use both" in result.output

    @respx.mock
    @patch("dhub.core.install.save_installed_version")
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.core.install.get_installed_version", return_value="1.0.0")
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_update_single_skill_outdated(
        self,
        _mock_url,
        _mock_token,
        _mock_installed_ver,
        mock_skill_path,
        _mock_checksum,
        _mock_save_ver,
        tmp_path: Path,
    ) -> None:
        """Single skill update when a newer version is available."""
        skill_dir = tmp_path / "myorg" / "my-skill"
        mock_skill_path.return_value = skill_dir

        zip_bytes = _make_zip_bytes()

        # Resolve for the update check
        respx.get("http://test:8000/v1/resolve/myorg/my-skill").mock(
            return_value=httpx.Response(
                200,
                json={
                    "version": "2.0.0",
                    "download_url": "http://test:8000/download/skill.zip",
                    "checksum": "abc123",
                },
            )
        )
        respx.get("http://test:8000/download/skill.zip").mock(
            return_value=httpx.Response(200, content=zip_bytes)
        )

        result = runner.invoke(app, ["update", "myorg/my-skill"])

        assert result.exit_code == 0
        assert "1.0.0" in result.output
        assert "2.0.0" in result.output
        assert "Installed" in result.output

    @respx.mock
    @patch("dhub.core.install.get_installed_version", return_value="2.0.0")
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_update_single_skill_already_current(
        self,
        _mock_url,
        _mock_token,
        _mock_installed_ver,
    ) -> None:
        """Single skill update when already at latest version."""
        respx.get("http://test:8000/v1/resolve/myorg/my-skill").mock(
            return_value=httpx.Response(
                200,
                json={
                    "version": "2.0.0",
                    "download_url": "http://test:8000/download/skill.zip",
                    "checksum": "abc123",
                },
            )
        )

        result = runner.invoke(app, ["update", "myorg/my-skill"])

        assert result.exit_code == 0
        assert "up to date" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_update_single_skill_not_found(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        """Single skill update when skill is not in registry."""
        respx.get("http://test:8000/v1/resolve/myorg/gone-skill").mock(
            return_value=httpx.Response(404)
        )

        result = runner.invoke(app, ["update", "myorg/gone-skill"])

        assert result.exit_code == 1
        assert "not found" in result.output

    @patch("dhub.core.install.list_installed_skills", return_value=[])
    def test_update_all_no_skills_installed(self, _mock_list) -> None:
        """--all with no installed skills should print a helpful message."""
        result = runner.invoke(app, ["update", "--all"])

        assert result.exit_code == 0
        assert "No skills installed" in result.output

    @respx.mock
    @patch("dhub.core.install.save_installed_version")
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch(
        "dhub.core.install.list_installed_skills",
        return_value=[("myorg", "skill-a"), ("myorg", "skill-b")],
    )
    @patch("dhub.core.install.get_installed_version")
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_update_all_mixed(
        self,
        _mock_url,
        _mock_token,
        mock_installed_ver,
        _mock_list,
        mock_skill_path,
        _mock_checksum,
        _mock_save_ver,
        tmp_path: Path,
    ) -> None:
        """--all updates outdated skills and skips current ones."""
        # skill-a is outdated, skill-b is current
        mock_installed_ver.side_effect = lambda org, name: "1.0.0" if name == "skill-a" else "2.0.0"
        mock_skill_path.return_value = tmp_path / "myorg" / "skill-a"

        zip_bytes = _make_zip_bytes()

        def resolve_handler(request):
            if "skill-a" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "version": "1.1.0",
                        "download_url": "http://test:8000/download/a.zip",
                        "checksum": "abc",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "version": "2.0.0",
                    "download_url": "http://test:8000/download/b.zip",
                    "checksum": "def",
                },
            )

        respx.get("http://test:8000/v1/resolve/myorg/skill-a").mock(side_effect=resolve_handler)
        respx.get("http://test:8000/v1/resolve/myorg/skill-b").mock(side_effect=resolve_handler)
        respx.get("http://test:8000/download/a.zip").mock(
            return_value=httpx.Response(200, content=zip_bytes)
        )

        result = runner.invoke(app, ["update", "--all"])

        assert result.exit_code == 0
        assert "1 updated" in result.output
        assert "1 up to date" in result.output

    @respx.mock
    @patch("dhub.core.install.save_installed_version")
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch(
        "dhub.core.install.list_installed_skills",
        return_value=[("myorg", "legacy-skill")],
    )
    @patch("dhub.core.install.get_installed_version", return_value=None)
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_update_all_legacy_skill_no_version(
        self,
        _mock_url,
        _mock_token,
        _mock_installed_ver,
        _mock_list,
        mock_skill_path,
        _mock_checksum,
        _mock_save_ver,
        tmp_path: Path,
    ) -> None:
        """Legacy skills without a version file should always be updated."""
        mock_skill_path.return_value = tmp_path / "myorg" / "legacy-skill"

        zip_bytes = _make_zip_bytes()

        respx.get("http://test:8000/v1/resolve/myorg/legacy-skill").mock(
            return_value=httpx.Response(
                200,
                json={
                    "version": "1.0.0",
                    "download_url": "http://test:8000/download/legacy.zip",
                    "checksum": "abc",
                },
            )
        )
        respx.get("http://test:8000/download/legacy.zip").mock(
            return_value=httpx.Response(200, content=zip_bytes)
        )

        result = runner.invoke(app, ["update", "--all"])

        assert result.exit_code == 0
        assert "unknown" in result.output
        assert "1 updated" in result.output


class TestVersionTracking:
    def test_save_and_get_installed_version(self, tmp_path: Path) -> None:
        """save_installed_version writes a file that get_installed_version reads."""
        from dhub.core.install import get_installed_version, save_installed_version

        with patch("dhub.core.install.get_dhub_skill_path", return_value=tmp_path / "org" / "skill"):
            skill_dir = tmp_path / "org" / "skill"
            skill_dir.mkdir(parents=True)
            save_installed_version("org", "skill", "1.2.3")
            assert get_installed_version("org", "skill") == "1.2.3"

    def test_get_installed_version_missing(self, tmp_path: Path) -> None:
        """get_installed_version returns None when no version file exists."""
        from dhub.core.install import get_installed_version

        with patch("dhub.core.install.get_dhub_skill_path", return_value=tmp_path / "org" / "skill"):
            skill_dir = tmp_path / "org" / "skill"
            skill_dir.mkdir(parents=True)
            assert get_installed_version("org", "skill") is None

    def test_list_installed_skills(self, tmp_path: Path) -> None:
        """list_installed_skills scans the skills directory."""
        from dhub.core.install import list_installed_skills

        # Create fake skill directories
        (tmp_path / "org1" / "skill-a").mkdir(parents=True)
        (tmp_path / "org1" / "skill-a" / "SKILL.md").write_text("content")
        (tmp_path / "org2" / "skill-b").mkdir(parents=True)
        (tmp_path / "org2" / "skill-b" / "SKILL.md").write_text("content")
        # Empty dir should be skipped
        (tmp_path / "org2" / "empty").mkdir(parents=True)

        with patch("dhub.core.install.Path.home", return_value=tmp_path / "fake-home"):
            # We need to create the .dhub/skills structure under the fake home
            skills_root = tmp_path / "fake-home" / ".dhub" / "skills"
            skills_root.mkdir(parents=True)

            (skills_root / "org1" / "skill-a").mkdir(parents=True)
            (skills_root / "org1" / "skill-a" / "SKILL.md").write_text("content")
            (skills_root / "org2" / "skill-b").mkdir(parents=True)
            (skills_root / "org2" / "skill-b" / "SKILL.md").write_text("content")
            (skills_root / "org2" / "empty").mkdir(parents=True)

            result = list_installed_skills()

        assert ("org1", "skill-a") in result
        assert ("org2", "skill-b") in result
        assert ("org2", "empty") not in result
