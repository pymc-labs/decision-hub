"""Regression tests: every public read endpoint enforces a rate limit.

CLAUDE.md mandates that public endpoints always carry a per-IP limiter.
These tests guard against the next public endpoint being shipped without one
by exercising each route past its configured limit and asserting HTTP 429.

We override the rate-limit settings to tiny windows so the tests stay fast.
The shared limiter cache lives on ``app.state``, so each test gets its own
``client`` (and thus its own app + state) via the conftest fixtures.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def tight_settings(test_settings):
    """Override read-endpoint limits to 1 request per 60s."""
    test_settings.stats_rate_limit = 1
    test_settings.skill_summary_rate_limit = 1
    test_settings.resolve_rate_limit = 1
    test_settings.eval_report_rate_limit = 1
    test_settings.taxonomy_rate_limit = 1
    return test_settings


def test_taxonomy_rate_limited(tight_settings, client: TestClient) -> None:
    assert client.get("/v1/taxonomy").status_code == 200
    assert client.get("/v1/taxonomy").status_code == 429


def test_stats_rate_limited(tight_settings, client: TestClient) -> None:
    with patch("decision_hub.api.registry_routes.fetch_registry_stats") as fetch:
        fetch.return_value = {"total_skills": 0, "total_orgs": 0, "total_downloads": 0}
        assert client.get("/v1/stats").status_code == 200
        assert client.get("/v1/stats").status_code == 429


def test_skill_summary_rate_limited(tight_settings, client: TestClient) -> None:
    with patch("decision_hub.api.registry_routes.find_skill_by_slug") as find:
        # 404 path is fine; we only care that the limiter ran.
        find.return_value = None
        assert client.get("/v1/skills/acme/widget/summary").status_code == 404
        assert client.get("/v1/skills/acme/widget/summary").status_code == 429


def test_latest_version_rate_limited(tight_settings, client: TestClient) -> None:
    with patch("decision_hub.api.registry_routes.resolve_latest_version") as resolve:
        resolve.return_value = None
        assert client.get("/v1/skills/acme/widget/latest-version").status_code == 404
        assert client.get("/v1/skills/acme/widget/latest-version").status_code == 429


def test_eval_report_query_form_rate_limited(tight_settings, client: TestClient) -> None:
    with patch("decision_hub.api.registry_routes.find_skill_by_slug") as find:
        find.return_value = MagicMock(visibility="public")
        with patch(
            "decision_hub.api.registry_routes.find_eval_report_by_skill",
            return_value=None,
        ):
            url = "/v1/skills/acme/widget/eval-report?semver=1.0.0"
            assert client.get(url).status_code == 200
            assert client.get(url).status_code == 429


def test_eval_report_path_form_rate_limited(tight_settings, client: TestClient) -> None:
    with patch("decision_hub.api.registry_routes.find_skill_by_slug") as find:
        find.return_value = MagicMock(visibility="public")
        with patch(
            "decision_hub.api.registry_routes.find_eval_report_by_skill",
            return_value=None,
        ):
            url = "/v1/skills/acme/widget/versions/1.0.0/eval-report"
            assert client.get(url).status_code == 200
            assert client.get(url).status_code == 429
