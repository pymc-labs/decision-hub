"""Tests for GET /skills/{org}/{name}/eval-report endpoint.

Covers:
- Report found → returns full EvalReportResponse
- Report not found → returns null
- Skill not found → 404
- Path-based variant (/versions/{semver}/eval-report)
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from decision_hub.models import EvalReport


def _make_eval_report(**overrides) -> EvalReport:
    """Create an EvalReport with sensible defaults."""
    defaults = {
        "id": uuid4(),
        "version_id": uuid4(),
        "agent": "claude",
        "judge_model": "claude-sonnet-4-5-20250929",
        "case_results": [
            {
                "name": "basic-test",
                "description": "Run basic analysis",
                "verdict": "pass",
                "reasoning": "Agent produced correct output",
                "agent_output": "Analysis complete",
                "agent_stderr": "",
                "exit_code": 0,
                "duration_ms": 5000,
                "stage": "judge",
            }
        ],
        "passed": 1,
        "total": 1,
        "total_duration_ms": 5000,
        "status": "completed",
        "error_message": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return EvalReport(**defaults)


class TestGetEvalReportBySkill:
    """GET /skills/{org}/{name}/eval-report?semver=X.Y.Z"""

    @patch("decision_hub.api.registry_routes.find_eval_report_by_skill")
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    @patch("decision_hub.api.registry_routes.list_user_org_ids")
    def test_returns_report_when_found(
        self,
        mock_list_org_ids: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_report: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ):
        """Returns full eval report when skill and report exist."""
        mock_list_org_ids.return_value = [uuid4()]
        mock_find_skill.return_value = MagicMock(id=uuid4())

        report = _make_eval_report()
        mock_find_report.return_value = report

        resp = client.get(
            "/v1/skills/test-org/test-skill/eval-report?semver=1.0.0",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(report.id)
        assert data["agent"] == "claude"
        assert data["passed"] == 1
        assert data["total"] == 1
        assert data["status"] == "completed"
        assert len(data["case_results"]) == 1
        assert data["case_results"][0]["verdict"] == "pass"

    @patch("decision_hub.api.registry_routes.find_eval_report_by_skill")
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    @patch("decision_hub.api.registry_routes.list_user_org_ids")
    def test_returns_null_when_no_report(
        self,
        mock_list_org_ids: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_report: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ):
        """Returns null when skill exists but no eval report found."""
        mock_list_org_ids.return_value = [uuid4()]
        mock_find_skill.return_value = MagicMock(id=uuid4())
        mock_find_report.return_value = None

        resp = client.get(
            "/v1/skills/test-org/test-skill/eval-report?semver=1.0.0",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        assert resp.json() is None

    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    @patch("decision_hub.api.registry_routes.list_user_org_ids")
    def test_returns_404_when_skill_not_found(
        self,
        mock_list_org_ids: MagicMock,
        mock_find_skill: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ):
        """Returns 404 when the skill doesn't exist."""
        mock_list_org_ids.return_value = [uuid4()]
        mock_find_skill.return_value = None

        resp = client.get(
            "/v1/skills/test-org/nonexistent-skill/eval-report?semver=1.0.0",
            headers=auth_headers,
        )

        assert resp.status_code == 404

    @patch("decision_hub.api.registry_routes.find_eval_report_by_skill")
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    @patch("decision_hub.api.registry_routes.list_user_org_ids")
    def test_failed_report_includes_error_message(
        self,
        mock_list_org_ids: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_report: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ):
        """Failed eval report includes the error message."""
        mock_list_org_ids.return_value = [uuid4()]
        mock_find_skill.return_value = MagicMock(id=uuid4())

        report = _make_eval_report(
            status="failed",
            error_message="ANTHROPIC_API_KEY is invalid",
            case_results=[],
            passed=0,
            total=2,
        )
        mock_find_report.return_value = report

        resp = client.get(
            "/v1/skills/test-org/test-skill/eval-report?semver=1.0.0",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"
        assert data["error_message"] == "ANTHROPIC_API_KEY is invalid"
        assert data["passed"] == 0


class TestGetEvalReportByVersionPath:
    """GET /v1/skills/{org}/{name}/versions/{semver}/eval-report"""

    @patch("decision_hub.api.registry_routes.find_eval_report_by_skill")
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    @patch("decision_hub.api.registry_routes.list_user_org_ids")
    def test_path_based_variant_returns_report(
        self,
        mock_list_org_ids: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_report: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ):
        """Path-based endpoint returns the same report as query-param variant."""
        mock_list_org_ids.return_value = [uuid4()]
        mock_find_skill.return_value = MagicMock(id=uuid4())

        report = _make_eval_report()
        mock_find_report.return_value = report

        resp = client.get(
            "/v1/skills/test-org/test-skill/versions/1.0.0/eval-report",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(report.id)
        assert data["status"] == "completed"

    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    @patch("decision_hub.api.registry_routes.list_user_org_ids")
    def test_path_based_variant_404_for_missing_skill(
        self,
        mock_list_org_ids: MagicMock,
        mock_find_skill: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ):
        """Path-based variant returns 404 for missing skill."""
        mock_list_org_ids.return_value = [uuid4()]
        mock_find_skill.return_value = None

        resp = client.get(
            "/v1/skills/test-org/nonexistent/versions/1.0.0/eval-report",
            headers=auth_headers,
        )

        assert resp.status_code == 404

    @patch("decision_hub.api.registry_routes.find_eval_report_by_skill")
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    @patch("decision_hub.api.registry_routes.list_user_org_ids")
    def test_path_based_variant_null_for_no_report(
        self,
        mock_list_org_ids: MagicMock,
        mock_find_skill: MagicMock,
        mock_find_report: MagicMock,
        client: TestClient,
        auth_headers: dict[str, str],
    ):
        """Path-based variant returns null when no report exists."""
        mock_list_org_ids.return_value = [uuid4()]
        mock_find_skill.return_value = MagicMock(id=uuid4())
        mock_find_report.return_value = None

        resp = client.get(
            "/v1/skills/test-org/test-skill/versions/2.0.0/eval-report",
            headers=auth_headers,
        )

        assert resp.status_code == 200
        assert resp.json() is None
