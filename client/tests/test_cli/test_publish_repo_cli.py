"""Tests for dhub publish with git repository URLs."""

from pathlib import Path
from unittest.mock import patch

import httpx
import respx
from typer.testing import CliRunner

from dhub.cli.app import app
from dhub.core.git_repo import looks_like_git_url

runner = CliRunner()


def _write_skill_md(directory: Path, name: str = "test-skill") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(f"---\nname: {name}\ndescription: A test skill\n---\nBody text\n")


class TestLooksLikeGitUrl:
    def test_https_url(self) -> None:
        assert looks_like_git_url("https://github.com/org/repo") is True

    def test_http_url(self) -> None:
        assert looks_like_git_url("http://github.com/org/repo") is True

    def test_ssh_url(self) -> None:
        assert looks_like_git_url("git@github.com:org/repo.git") is True

    def test_ssh_scheme_url(self) -> None:
        assert looks_like_git_url("ssh://git@github.com/org/repo") is True

    def test_git_scheme_url(self) -> None:
        assert looks_like_git_url("git://github.com/org/repo") is True

    def test_dot_git_suffix(self) -> None:
        assert looks_like_git_url("org/repo.git") is True

    def test_org_skill_ref(self) -> None:
        assert looks_like_git_url("myorg/my-skill") is False

    def test_local_path(self) -> None:
        assert looks_like_git_url("./my-skill") is False

    def test_bare_name(self) -> None:
        assert looks_like_git_url("my-skill") is False


class TestPublishFromGitRepo:
    @respx.mock
    @patch("dhub.core.git_repo.clone_repo")
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_git_single_skill(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        mock_clone,
        tmp_path: Path,
    ) -> None:
        """Discovers and publishes a single skill from a git repo."""
        repo_root = tmp_path / "repo"
        _write_skill_md(repo_root / "my-skill", name="my-skill")
        mock_clone.return_value = repo_root

        respx.get("http://test:8000/v1/skills/myorg/my-skill/latest-version").mock(return_value=httpx.Response(404))
        respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={"eval_status": "A"}))

        result = runner.invoke(
            app,
            ["publish", "https://github.com/example/repo"],
        )

        assert result.exit_code == 0
        assert "1 skill(s)" in result.output
        assert "my-skill" in result.output
        assert "1 published" in result.output

    @respx.mock
    @patch("dhub.core.git_repo.clone_repo")
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_git_multiple_skills(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        mock_clone,
        tmp_path: Path,
    ) -> None:
        """Discovers and publishes multiple skills from a git repo."""
        repo_root = tmp_path / "repo"
        _write_skill_md(repo_root / "skills" / "alpha", name="alpha")
        _write_skill_md(repo_root / "skills" / "beta", name="beta")
        mock_clone.return_value = repo_root

        respx.get("http://test:8000/v1/skills/myorg/alpha/latest-version").mock(return_value=httpx.Response(404))
        respx.get("http://test:8000/v1/skills/myorg/beta/latest-version").mock(return_value=httpx.Response(404))
        respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={"eval_status": "A"}))

        result = runner.invoke(
            app,
            ["publish", "https://github.com/example/repo"],
        )

        assert result.exit_code == 0
        assert "2 skill(s)" in result.output
        assert "2 published" in result.output

    @patch("dhub.core.git_repo.clone_repo")
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_git_no_skills_found(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        mock_clone,
        tmp_path: Path,
    ) -> None:
        """Exits with error when no skills are found in the repo."""
        repo_root = tmp_path / "repo"
        repo_root.mkdir(parents=True)
        (repo_root / "README.md").write_text("# No skills here\n")
        mock_clone.return_value = repo_root

        result = runner.invoke(
            app,
            ["publish", "https://github.com/example/repo"],
        )

        assert result.exit_code == 1
        assert "No skills found" in result.output

    @patch("dhub.core.git_repo.clone_repo", side_effect=RuntimeError("git clone failed (exit 128):\nfatal: not a repo"))
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_git_clone_failure(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        _mock_clone,
    ) -> None:
        """Exits with error when git clone fails."""
        result = runner.invoke(
            app,
            ["publish", "https://github.com/example/repo"],
        )

        assert result.exit_code == 1
        assert "git clone failed" in result.output

    @respx.mock
    @patch("dhub.core.git_repo.clone_repo")
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_git_with_ref(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        mock_clone,
        tmp_path: Path,
    ) -> None:
        """--ref is passed through to clone_repo."""
        repo_root = tmp_path / "repo"
        _write_skill_md(repo_root, name="my-skill")
        mock_clone.return_value = repo_root

        respx.get("http://test:8000/v1/skills/myorg/my-skill/latest-version").mock(return_value=httpx.Response(404))
        respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={"eval_status": "A"}))

        result = runner.invoke(
            app,
            ["publish", "https://github.com/example/repo", "--ref", "v2.0"],
        )

        assert result.exit_code == 0
        mock_clone.assert_called_once_with("https://github.com/example/repo", ref="v2.0")

    @respx.mock
    @patch("dhub.core.git_repo.clone_repo")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_git_auto_detects_org(
        self,
        _mock_url,
        _mock_token,
        mock_clone,
        tmp_path: Path,
    ) -> None:
        """Auto-detects org when publishing from git URL."""
        repo_root = tmp_path / "repo"
        _write_skill_md(repo_root, name="my-skill")
        mock_clone.return_value = repo_root

        respx.get("http://test:8000/v1/orgs").mock(return_value=httpx.Response(200, json=[{"slug": "auto-org"}]))
        respx.get("http://test:8000/v1/skills/auto-org/my-skill/latest-version").mock(return_value=httpx.Response(404))
        respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={"eval_status": "A"}))

        with (
            patch("dhub.cli.config.load_config") as mock_config,
            patch("dhub.cli.config.get_default_org", return_value=None),
        ):
            mock_config.return_value.orgs = []

            result = runner.invoke(
                app,
                ["publish", "https://github.com/example/repo"],
            )

        assert result.exit_code == 0
        assert "auto-org" in result.output

    @respx.mock
    @patch("dhub.core.git_repo.clone_repo")
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_git_continues_on_failure(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        mock_clone,
        tmp_path: Path,
    ) -> None:
        """Continues publishing remaining skills when one fails."""
        repo_root = tmp_path / "repo"
        _write_skill_md(repo_root / "alpha", name="alpha")
        _write_skill_md(repo_root / "beta", name="beta")
        mock_clone.return_value = repo_root

        respx.get("http://test:8000/v1/skills/myorg/alpha/latest-version").mock(return_value=httpx.Response(404))
        respx.get("http://test:8000/v1/skills/myorg/beta/latest-version").mock(return_value=httpx.Response(404))
        # First publish fails with 409, second succeeds
        publish_route = respx.post("http://test:8000/v1/publish")
        publish_route.side_effect = [
            httpx.Response(409),
            httpx.Response(200, json={"eval_status": "A"}),
        ]

        result = runner.invoke(
            app,
            ["publish", "https://github.com/example/repo"],
        )

        assert result.exit_code == 1
        assert "1 published" in result.output
        assert "1 failed" in result.output

    def test_ref_without_git_url_rejected(self, tmp_path: Path) -> None:
        """--ref should be rejected when not publishing from a git URL."""
        _write_skill_md(tmp_path)

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--ref", "main"],
        )

        assert result.exit_code == 1
        assert "--ref can only be used with a git repository URL" in result.output

    @respx.mock
    @patch("dhub.core.git_repo.clone_repo")
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_ssh_git_url(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        mock_clone,
        tmp_path: Path,
    ) -> None:
        """SSH git@ URLs are detected as git repos."""
        repo_root = tmp_path / "repo"
        _write_skill_md(repo_root, name="my-skill")
        mock_clone.return_value = repo_root

        respx.get("http://test:8000/v1/skills/myorg/my-skill/latest-version").mock(return_value=httpx.Response(404))
        respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={"eval_status": "A"}))

        result = runner.invoke(
            app,
            ["publish", "git@github.com:example/repo.git"],
        )

        assert result.exit_code == 0
        mock_clone.assert_called_once_with("git@github.com:example/repo.git", ref=None)
