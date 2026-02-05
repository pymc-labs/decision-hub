"""Tests for decision_hub.cli.org -- organization management commands."""

from unittest.mock import MagicMock, patch

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


def _ok_response(json_data: dict | list | None = None, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.raise_for_status = MagicMock()
    return resp


def _error_response(status_code: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# org create
# ---------------------------------------------------------------------------

class TestCreateOrg:

    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.org.httpx.Client")
    def test_create_org_success(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        mock_client_cls.return_value = _make_mock_client(
            _ok_response({"slug": "my-org"})
        )

        result = runner.invoke(app, ["org", "create", "my-org"])

        assert result.exit_code == 0
        assert "Created organization: my-org" in result.output

    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.org.httpx.Client")
    def test_create_org_409_conflict(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        mock_client_cls.return_value = _make_mock_client(_error_response(409))

        result = runner.invoke(app, ["org", "create", "my-org"])

        assert result.exit_code == 1
        assert "already exists" in result.output


# ---------------------------------------------------------------------------
# org list
# ---------------------------------------------------------------------------

class TestListOrgs:

    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.org.httpx.Client")
    def test_list_orgs_with_results(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        orgs = [
            {"slug": "alpha-org", "role": "owner"},
            {"slug": "beta-org", "role": "member"},
        ]
        mock_client_cls.return_value = _make_mock_client(_ok_response(orgs))

        result = runner.invoke(app, ["org", "list"])

        assert result.exit_code == 0
        assert "alpha-org" in result.output
        assert "beta-org" in result.output
        assert "owner" in result.output
        assert "member" in result.output

    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.org.httpx.Client")
    def test_list_orgs_empty(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        mock_client_cls.return_value = _make_mock_client(_ok_response([]))

        result = runner.invoke(app, ["org", "list"])

        assert result.exit_code == 0
        assert "not a member" in result.output


# ---------------------------------------------------------------------------
# org invite
# ---------------------------------------------------------------------------

class TestInviteMember:

    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.org.httpx.Client")
    def test_invite_success(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        mock_client_cls.return_value = _make_mock_client(
            _ok_response({"id": "inv-abc-123"})
        )

        result = runner.invoke(
            app, ["org", "invite", "my-org", "--user", "jchu", "--role", "admin"]
        )

        assert result.exit_code == 0
        assert "Invited @jchu" in result.output
        assert "my-org" in result.output
        assert "admin" in result.output
        assert "inv-abc-123" in result.output

    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.org.httpx.Client")
    def test_invite_403_forbidden(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        mock_client_cls.return_value = _make_mock_client(_error_response(403))

        result = runner.invoke(
            app, ["org", "invite", "my-org", "--user", "jchu", "--role", "admin"]
        )

        assert result.exit_code == 1
        assert "permission" in result.output.lower()


# ---------------------------------------------------------------------------
# org accept
# ---------------------------------------------------------------------------

class TestAcceptInvite:

    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.org.httpx.Client")
    def test_accept_invite_success(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        mock_client_cls.return_value = _make_mock_client(
            _ok_response({"org_slug": "cool-org"})
        )

        result = runner.invoke(app, ["org", "accept", "inv-abc-123"])

        assert result.exit_code == 0
        assert "Accepted invite" in result.output
        assert "cool-org" in result.output

    @patch("decision_hub.cli.config.get_token", return_value="test-token")
    @patch("decision_hub.cli.config.get_api_url", return_value="http://test:8000")
    @patch("decision_hub.cli.org.httpx.Client")
    def test_accept_invite_404(
        self,
        mock_client_cls: MagicMock,
        _mock_url: MagicMock,
        _mock_token: MagicMock,
    ) -> None:
        mock_client_cls.return_value = _make_mock_client(_error_response(404))

        result = runner.invoke(app, ["org", "accept", "inv-nonexistent"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()
