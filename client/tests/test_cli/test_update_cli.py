"""Tests for dhub update command."""

import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx
import respx
from typer.testing import CliRunner

from dhub.cli.app import app
from dhub.core.install import InstalledVersion

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
    @patch("dhub.core.install.get_installed_version", return_value=InstalledVersion("1.0.0"))
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
        skill_dir.mkdir(parents=True)
        mock_skill_path.return_value = skill_dir

        zip_bytes = _make_zip_bytes()

        # /latest-version for the version check (no download count)
        respx.get("http://test:8000/v1/skills/myorg/my-skill/latest-version").mock(
            return_value=httpx.Response(200, json={"version": "2.0.0", "checksum": "abc123"})
        )
        # /resolve only called when update is needed
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
        respx.get("http://test:8000/download/skill.zip").mock(return_value=httpx.Response(200, content=zip_bytes))

        result = runner.invoke(app, ["update", "myorg/my-skill"])

        assert result.exit_code == 0
        assert "1.0.0" in result.output
        assert "2.0.0" in result.output
        assert "Installed" in result.output

    @respx.mock
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.core.install.get_installed_version", return_value=InstalledVersion("2.0.0"))
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_update_single_skill_already_current(
        self,
        _mock_url,
        _mock_token,
        _mock_installed_ver,
        mock_skill_path,
        tmp_path: Path,
    ) -> None:
        """Single skill update when already at latest version."""
        skill_dir = tmp_path / "myorg" / "my-skill"
        skill_dir.mkdir(parents=True)
        mock_skill_path.return_value = skill_dir

        # Only /latest-version is called; /resolve should NOT be called
        respx.get("http://test:8000/v1/skills/myorg/my-skill/latest-version").mock(
            return_value=httpx.Response(200, json={"version": "2.0.0", "checksum": "abc123"})
        )

        result = runner.invoke(app, ["update", "myorg/my-skill"])

        assert result.exit_code == 0
        assert "up to date" in result.output

    @patch("dhub.core.install.get_dhub_skill_path")
    def test_update_single_skill_not_installed(
        self,
        mock_skill_path,
        tmp_path: Path,
    ) -> None:
        """Update for a skill that is not installed locally should error."""
        # Point to a non-existent directory
        mock_skill_path.return_value = tmp_path / "myorg" / "not-installed"

        result = runner.invoke(app, ["update", "myorg/not-installed"])

        assert result.exit_code == 1
        assert "not installed" in result.output
        assert "dhub install" in result.output

    @respx.mock
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_update_single_skill_not_found(
        self,
        _mock_url,
        _mock_token,
        mock_skill_path,
        tmp_path: Path,
    ) -> None:
        """Single skill update when skill is not in registry."""
        skill_dir = tmp_path / "myorg" / "gone-skill"
        skill_dir.mkdir(parents=True)
        mock_skill_path.return_value = skill_dir

        respx.get("http://test:8000/v1/skills/myorg/gone-skill/latest-version").mock(return_value=httpx.Response(404))

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
        mock_installed_ver.side_effect = lambda org, name: (
            InstalledVersion("1.0.0") if name == "skill-a" else InstalledVersion("2.0.0")
        )
        mock_skill_path.return_value = tmp_path / "myorg" / "skill-a"

        zip_bytes = _make_zip_bytes()

        # /latest-version for both skills (version check, no download inflation)
        respx.get("http://test:8000/v1/skills/myorg/skill-a/latest-version").mock(
            return_value=httpx.Response(200, json={"version": "1.1.0", "checksum": "abc"})
        )
        respx.get("http://test:8000/v1/skills/myorg/skill-b/latest-version").mock(
            return_value=httpx.Response(200, json={"version": "2.0.0", "checksum": "def"})
        )
        # /resolve only called for skill-a (needs update); skill-b is up to date
        respx.get("http://test:8000/v1/resolve/myorg/skill-a").mock(
            return_value=httpx.Response(
                200,
                json={
                    "version": "1.1.0",
                    "download_url": "http://test:8000/download/a.zip",
                    "checksum": "abc",
                },
            )
        )
        respx.get("http://test:8000/download/a.zip").mock(return_value=httpx.Response(200, content=zip_bytes))

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

        respx.get("http://test:8000/v1/skills/myorg/legacy-skill/latest-version").mock(
            return_value=httpx.Response(200, json={"version": "1.0.0", "checksum": "abc"})
        )
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
        respx.get("http://test:8000/download/legacy.zip").mock(return_value=httpx.Response(200, content=zip_bytes))

        result = runner.invoke(app, ["update", "--all"])

        assert result.exit_code == 0
        assert "unknown" in result.output
        assert "1 updated" in result.output

    @respx.mock
    @patch("dhub.core.install.save_installed_version")
    @patch("dhub.core.install.verify_checksum")
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.core.install.get_installed_version", return_value=InstalledVersion("1.0.0", allow_risky=True))
    @patch("dhub.cli.config.get_optional_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_update_single_risky_skill(
        self,
        _mock_url,
        _mock_token,
        _mock_installed_ver,
        mock_skill_path,
        _mock_checksum,
        _mock_save_ver,
        tmp_path: Path,
    ) -> None:
        """A skill installed with --allow-risky should resolve with allow_risky=true."""
        skill_dir = tmp_path / "myorg" / "risky-skill"
        skill_dir.mkdir(parents=True)
        mock_skill_path.return_value = skill_dir

        zip_bytes = _make_zip_bytes()

        respx.get("http://test:8000/v1/skills/myorg/risky-skill/latest-version").mock(
            return_value=httpx.Response(200, json={"version": "2.0.0", "checksum": "abc"})
        )

        # The resolve call must include allow_risky=true
        resolve_route = respx.get("http://test:8000/v1/resolve/myorg/risky-skill").mock(
            return_value=httpx.Response(
                200,
                json={
                    "version": "2.0.0",
                    "download_url": "http://test:8000/download/risky.zip",
                    "checksum": "abc",
                },
            )
        )
        respx.get("http://test:8000/download/risky.zip").mock(return_value=httpx.Response(200, content=zip_bytes))

        result = runner.invoke(app, ["update", "myorg/risky-skill"])

        assert result.exit_code == 0
        assert "Installed" in result.output
        # Verify allow_risky was passed in the resolve request
        assert resolve_route.called
        assert "allow_risky=true" in str(resolve_route.calls[0].request.url)


class TestVersionTracking:
    def test_save_and_get_installed_version(self, tmp_path: Path) -> None:
        """save_installed_version writes a file that get_installed_version reads."""
        from dhub.core.install import get_installed_version, save_installed_version

        with patch("dhub.core.install.get_dhub_skill_path", return_value=tmp_path / "org" / "skill"):
            skill_dir = tmp_path / "org" / "skill"
            skill_dir.mkdir(parents=True)
            save_installed_version("org", "skill", "1.2.3")
            result = get_installed_version("org", "skill")
            assert result is not None
            assert result.version == "1.2.3"
            assert result.allow_risky is False

    def test_save_and_get_risky_version(self, tmp_path: Path) -> None:
        """allow_risky flag is persisted and read back correctly."""
        from dhub.core.install import get_installed_version, save_installed_version

        with patch("dhub.core.install.get_dhub_skill_path", return_value=tmp_path / "org" / "skill"):
            skill_dir = tmp_path / "org" / "skill"
            skill_dir.mkdir(parents=True)
            save_installed_version("org", "skill", "1.0.0", allow_risky=True)
            result = get_installed_version("org", "skill")
            assert result is not None
            assert result.version == "1.0.0"
            assert result.allow_risky is True

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

        with patch("dhub.core.install.Path.home", return_value=tmp_path / "fake-home"):
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
