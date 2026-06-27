"""Tests for the rate limiters added to previously-unprotected public GETs.

The endpoints ``/v1/stats``, ``/v1/skills/{org}/{name}/summary``,
``/v1/skills/{org}/{name}/latest-version``, and the two ``/eval-report``
variants used to be public GETs with no rate limit, leaving the database
exposed to enumeration. Each now carries an ``_enforce_*_rate_limit``
dependency. The tests below set the per-endpoint cap to 2 and verify the
third request is rejected with HTTP 429.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def low_limit_client(test_settings, test_app) -> TestClient:
    """A TestClient whose per-endpoint caps are all set to 2.

    The matching ``app.state._*_rate_limiter`` slots are cleared so each
    test starts from a clean limiter built from the lowered settings.
    """
    for attr in (
        "stats_rate_limit",
        "skill_summary_rate_limit",
        "latest_version_rate_limit",
        "eval_report_rate_limit",
    ):
        setattr(test_settings, attr, 2)
    for slot in (
        "_stats_rate_limiter",
        "_skill_summary_rate_limiter",
        "_latest_version_rate_limiter",
        "_eval_report_rate_limiter",
    ):
        if hasattr(test_app.state, slot):
            delattr(test_app.state, slot)
    return TestClient(test_app)


class TestStatsRateLimit:
    @patch("decision_hub.api.registry_routes.fetch_registry_stats")
    def test_third_request_blocked(self, mock_stats, low_limit_client: TestClient) -> None:
        mock_stats.return_value = {"total_skills": 0, "total_orgs": 0, "total_downloads": 0}
        assert low_limit_client.get("/v1/stats").status_code == 200
        assert low_limit_client.get("/v1/stats").status_code == 200
        resp = low_limit_client.get("/v1/stats")
        assert resp.status_code == 429
        assert "Rate limit exceeded" in resp.json()["detail"]


class TestSkillSummaryRateLimit:
    @patch("decision_hub.api.registry_routes.has_active_tracker_for_repo", return_value=False)
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    @patch("decision_hub.api.registry_routes.resolve_latest_version")
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_third_request_blocked(
        self,
        mock_find,
        mock_resolve,
        mock_find_org,
        _mock_tracker,
        low_limit_client: TestClient,
    ) -> None:
        skill = MagicMock()
        skill.description = "x"
        skill.download_count = 0
        skill.category = ""
        skill.visibility = "public"
        skill.source_repo_url = None
        skill.manifest_path = None
        skill.source_repo_removed = False
        skill.github_stars = None
        skill.github_forks = None
        skill.github_watchers = None
        skill.github_is_archived = None
        skill.github_license = None
        mock_find.return_value = skill

        version = MagicMock()
        version.semver = "1.0.0"
        version.created_at = None
        version.eval_status = "A"
        version.published_by = "alice"
        mock_resolve.return_value = version
        mock_find_org.return_value = MagicMock(is_personal=False)

        path = "/v1/skills/test-org/test-skill/summary"
        assert low_limit_client.get(path).status_code == 200
        assert low_limit_client.get(path).status_code == 200
        assert low_limit_client.get(path).status_code == 429


class TestLatestVersionRateLimit:
    @patch("decision_hub.api.registry_routes.resolve_latest_version")
    def test_third_request_blocked(self, mock_resolve, low_limit_client: TestClient) -> None:
        version = MagicMock()
        version.semver = "1.0.0"
        version.checksum = "deadbeef"
        mock_resolve.return_value = version

        path = "/v1/skills/test-org/test-skill/latest-version"
        assert low_limit_client.get(path).status_code == 200
        assert low_limit_client.get(path).status_code == 200
        assert low_limit_client.get(path).status_code == 429


class TestEvalReportRateLimit:
    @patch("decision_hub.api.registry_routes.find_eval_report_by_skill", return_value=None)
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_third_query_param_request_blocked(
        self,
        mock_find,
        _mock_report,
        low_limit_client: TestClient,
    ) -> None:
        mock_find.return_value = MagicMock()
        path = "/v1/skills/test-org/test-skill/eval-report?semver=1.0.0"
        assert low_limit_client.get(path).status_code == 200
        assert low_limit_client.get(path).status_code == 200
        assert low_limit_client.get(path).status_code == 429

    @patch("decision_hub.api.registry_routes.find_eval_report_by_skill", return_value=None)
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_path_variant_shares_the_same_limiter(
        self,
        mock_find,
        _mock_report,
        low_limit_client: TestClient,
    ) -> None:
        """Both eval-report variants reuse the same limiter so two clients
        racing across both paths still trip the cap."""
        mock_find.return_value = MagicMock()
        query_path = "/v1/skills/test-org/test-skill/eval-report?semver=1.0.0"
        path_based = "/v1/skills/test-org/test-skill/versions/1.0.0/eval-report"
        assert low_limit_client.get(query_path).status_code == 200
        assert low_limit_client.get(path_based).status_code == 200
        assert low_limit_client.get(query_path).status_code == 429
