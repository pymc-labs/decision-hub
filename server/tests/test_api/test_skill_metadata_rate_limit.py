"""Regression tests for the skill metadata rate limiter.

Locks in the fix for missing rate limiters on four public endpoints:
 - GET /v1/skills/{org_slug}/{skill_name}/summary
 - GET /v1/skills/{org_slug}/{skill_name}/latest-version
 - GET /v1/skills/{org_slug}/{skill_name}/eval-report
 - GET /v1/skills/{org_slug}/{skill_name}/versions/{semver}/eval-report

Without a limiter these are trivially scrapable. They share one limiter
(``settings.skill_metadata_rate_limit``) so that a hostile client cannot
multiply quotas across endpoints.
"""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.factories import make_org, make_skill, make_version


def _set_low_limit(app: FastAPI, limit: int = 2) -> None:
    """Tighten the metadata limiter and discard any previously created instance."""
    app.state.settings.skill_metadata_rate_limit = limit
    app.state.settings.skill_metadata_rate_window = 60
    if hasattr(app.state, "_skill_metadata_rate_limiter"):
        delattr(app.state, "_skill_metadata_rate_limiter")


class TestSkillMetadataRateLimit:
    """All four metadata endpoints share a single per-IP sliding-window limiter."""

    @patch("decision_hub.api.registry_routes.has_active_tracker_for_repo", return_value=False)
    @patch("decision_hub.api.registry_routes.find_org_by_slug")
    @patch("decision_hub.api.registry_routes.resolve_latest_version")
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_summary_is_rate_limited(
        self,
        mock_find_skill,
        mock_resolve,
        mock_find_org,
        _mock_tracker,
        test_app: FastAPI,
    ) -> None:
        org = make_org()
        skill = make_skill(org)
        mock_find_org.return_value = org
        mock_find_skill.return_value = skill
        mock_resolve.return_value = make_version(skill)
        _set_low_limit(test_app, limit=2)
        client = TestClient(test_app)

        for _ in range(2):
            resp = client.get("/v1/skills/test-org/my-skill/summary")
            assert resp.status_code == 200

        resp = client.get("/v1/skills/test-org/my-skill/summary")
        assert resp.status_code == 429

    @patch("decision_hub.api.registry_routes.resolve_latest_version")
    def test_latest_version_is_rate_limited(
        self,
        mock_resolve,
        test_app: FastAPI,
    ) -> None:
        org = make_org()
        skill = make_skill(org)
        mock_resolve.return_value = make_version(skill)
        _set_low_limit(test_app, limit=2)
        client = TestClient(test_app)

        for _ in range(2):
            resp = client.get("/v1/skills/test-org/my-skill/latest-version")
            assert resp.status_code == 200

        resp = client.get("/v1/skills/test-org/my-skill/latest-version")
        assert resp.status_code == 429

    @patch("decision_hub.api.registry_routes.find_eval_report_by_skill", return_value=None)
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_eval_report_query_is_rate_limited(
        self,
        mock_find_skill,
        _mock_report,
        test_app: FastAPI,
    ) -> None:
        org = make_org()
        mock_find_skill.return_value = make_skill(org)
        _set_low_limit(test_app, limit=2)
        client = TestClient(test_app)

        for _ in range(2):
            resp = client.get("/v1/skills/test-org/my-skill/eval-report?semver=1.0.0")
            assert resp.status_code == 200

        resp = client.get("/v1/skills/test-org/my-skill/eval-report?semver=1.0.0")
        assert resp.status_code == 429

    @patch("decision_hub.api.registry_routes.find_eval_report_by_skill", return_value=None)
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_eval_report_path_is_rate_limited(
        self,
        mock_find_skill,
        _mock_report,
        test_app: FastAPI,
    ) -> None:
        org = make_org()
        mock_find_skill.return_value = make_skill(org)
        _set_low_limit(test_app, limit=2)
        client = TestClient(test_app)

        for _ in range(2):
            resp = client.get("/v1/skills/test-org/my-skill/versions/1.0.0/eval-report")
            assert resp.status_code == 200

        resp = client.get("/v1/skills/test-org/my-skill/versions/1.0.0/eval-report")
        assert resp.status_code == 429

    @patch("decision_hub.api.registry_routes.find_eval_report_by_skill", return_value=None)
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    @patch("decision_hub.api.registry_routes.resolve_latest_version")
    def test_limiter_is_shared_across_metadata_endpoints(
        self,
        mock_resolve,
        mock_find_skill,
        _mock_report,
        test_app: FastAPI,
    ) -> None:
        """A single limiter covers all four endpoints — the budget cannot be
        multiplied by alternating between them.
        """
        org = make_org()
        skill = make_skill(org)
        mock_find_skill.return_value = skill
        mock_resolve.return_value = make_version(skill)
        _set_low_limit(test_app, limit=2)
        client = TestClient(test_app)

        # First two requests across two different metadata endpoints fill the budget.
        assert client.get("/v1/skills/test-org/my-skill/latest-version").status_code == 200
        assert client.get("/v1/skills/test-org/my-skill/eval-report?semver=1.0.0").status_code == 200

        # Third request — to a *third* metadata endpoint — must still be rejected.
        resp = client.get("/v1/skills/test-org/my-skill/versions/1.0.0/eval-report")
        assert resp.status_code == 429
