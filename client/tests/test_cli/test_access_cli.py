"""Tests for dhub.cli.access -- access grant management commands."""

import json
from unittest.mock import patch

import httpx
import respx
from typer.testing import CliRunner

from dhub.cli.app import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# dhub access grant
# ---------------------------------------------------------------------------


class TestAccessGrant:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_grant_success(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.post("http://test:8000/v1/skills/myorg/my-skill/access").mock(
            return_value=httpx.Response(
                201,
                json={"org_slug": "myorg", "skill_name": "my-skill", "grantee_org_slug": "partner"},
            )
        )

        result = runner.invoke(app, ["access", "grant", "myorg/my-skill", "partner"])

        assert result.exit_code == 0
        assert "Granted access" in result.output
        assert "partner" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_grant_duplicate(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.post("http://test:8000/v1/skills/myorg/my-skill/access").mock(
            return_value=httpx.Response(409, json={"detail": "already granted"})
        )

        result = runner.invoke(app, ["access", "grant", "myorg/my-skill", "partner"])

        assert result.exit_code == 1
        assert "already granted" in result.output.lower()

    def test_grant_invalid_ref(self) -> None:
        result = runner.invoke(app, ["access", "grant", "noslash", "partner"])
        assert result.exit_code == 1
        assert "org/skill" in result.output.lower()


# ---------------------------------------------------------------------------
# dhub access revoke
# ---------------------------------------------------------------------------


class TestAccessRevoke:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_revoke_success(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.delete("http://test:8000/v1/skills/myorg/my-skill/access/partner").mock(
            return_value=httpx.Response(
                200,
                json={"org_slug": "myorg", "skill_name": "my-skill", "grantee_org_slug": "partner"},
            )
        )

        result = runner.invoke(app, ["access", "revoke", "myorg/my-skill", "partner"])

        assert result.exit_code == 0
        assert "Revoked access" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_revoke_not_found(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.delete("http://test:8000/v1/skills/myorg/my-skill/access/partner").mock(
            return_value=httpx.Response(404, json={"detail": "No access grant found"})
        )

        result = runner.invoke(app, ["access", "revoke", "myorg/my-skill", "partner"])

        assert result.exit_code == 1
        assert "No access grant found" in result.output


# ---------------------------------------------------------------------------
# dhub access list
# ---------------------------------------------------------------------------


class TestAccessList:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_empty(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.get("http://test:8000/v1/skills/myorg/my-skill/access").mock(return_value=httpx.Response(200, json=[]))

        result = runner.invoke(app, ["access", "list", "myorg/my-skill"])

        assert result.exit_code == 0
        assert "No access grants" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_list_with_grants(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.get("http://test:8000/v1/skills/myorg/my-skill/access").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "grantee_org_slug": "partner",
                        "granted_by": "admin-user",
                        "created_at": "2025-01-01T00:00:00",
                    }
                ],
            )
        )

        result = runner.invoke(app, ["access", "list", "myorg/my-skill"])

        assert result.exit_code == 0
        assert "partner" in result.output


# ---------------------------------------------------------------------------
# dhub access list JSON output
# ---------------------------------------------------------------------------


class TestAccessListJsonOutput:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_access_list_json(self, _mock_url, _mock_token) -> None:
        respx.get("http://test:8000/v1/skills/acme/my-skill/access").mock(
            return_value=httpx.Response(200, json=[
                {"grantee_org_slug": "partner", "granted_by": "alice", "created_at": "2026-01-01T00:00:00"}
            ])
        )
        result = runner.invoke(app, ["--output", "json", "access", "list", "acme/my-skill"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data[0]["grantee_org_slug"] == "partner"


# ---------------------------------------------------------------------------
# dhub visibility
# ---------------------------------------------------------------------------


class TestVisibilityCommand:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_set_org_private(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.put("http://test:8000/v1/skills/myorg/my-skill/visibility").mock(
            return_value=httpx.Response(
                200,
                json={"org_slug": "myorg", "skill_name": "my-skill", "visibility": "org"},
            )
        )

        result = runner.invoke(app, ["visibility", "myorg/my-skill", "org"])

        assert result.exit_code == 0
        assert "org-private" in result.output

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_set_public(
        self,
        _mock_url,
        _mock_token,
    ) -> None:
        respx.put("http://test:8000/v1/skills/myorg/my-skill/visibility").mock(
            return_value=httpx.Response(
                200,
                json={"org_slug": "myorg", "skill_name": "my-skill", "visibility": "public"},
            )
        )

        result = runner.invoke(app, ["visibility", "myorg/my-skill", "public"])

        assert result.exit_code == 0
        assert "public" in result.output

    def test_invalid_visibility_value(self) -> None:
        result = runner.invoke(app, ["visibility", "myorg/my-skill", "secret"])
        assert result.exit_code == 1
        assert "public" in result.output.lower() or "org" in result.output.lower()


# ---------------------------------------------------------------------------
# dhub publish --private
# ---------------------------------------------------------------------------


class TestPublishPrivateFlag:
    @respx.mock
    @patch("dhub.cli.registry._auto_detect_org", return_value="myorg")
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_publish_with_private_flag(
        self,
        _mock_url,
        _mock_token,
        _mock_org,
        tmp_path,
    ) -> None:

        (tmp_path / "SKILL.md").write_text("---\nname: test-skill\ndescription: A test skill\n---\nBody text\n")

        route = respx.post("http://test:8000/v1/publish").mock(return_value=httpx.Response(200, json={}))

        result = runner.invoke(
            app,
            ["publish", str(tmp_path), "--version", "1.0.0", "--private"],
        )

        assert result.exit_code == 0
        assert "Published: myorg/test-skill@1.0.0" in result.output
        assert "org-private" in result.output

        # Verify that the metadata included visibility=org

        call = route.calls[0]
        # The metadata is sent as form data; extract from the multipart body
        # Use the request content to verify
        request = call.request
        # The metadata field is in the multipart form — check the raw body
        body = request.content.decode("utf-8", errors="replace")
        assert '"visibility": "org"' in body or '"visibility":"org"' in body


# ---------------------------------------------------------------------------
# dhub access grant --dry-run
# ---------------------------------------------------------------------------


class TestAccessGrantDryRun:
    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_dry_run_no_post(self, _mock_url, _mock_token) -> None:
        respx.get("http://test:8000/v1/skills/acme/my-skill/access").mock(
            return_value=httpx.Response(200, json=[]))
        # No POST mock

        result = runner.invoke(app, ["access", "grant", "acme/my-skill", "partner", "--dry-run"])
        assert result.exit_code == 0
        assert "dry run" in result.output.lower() or "would grant" in result.output.lower()

    @respx.mock
    @patch("dhub.cli.config.get_token", return_value="test-token")
    @patch("dhub.cli.config.get_api_url", return_value="http://test:8000")
    def test_dry_run_json(self, _mock_url, _mock_token) -> None:
        respx.get("http://test:8000/v1/skills/acme/my-skill/access").mock(
            return_value=httpx.Response(200, json=[]))

        result = runner.invoke(app, ["--output", "json", "access", "grant", "acme/my-skill", "partner", "--dry-run"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["grantee"] == "partner"
