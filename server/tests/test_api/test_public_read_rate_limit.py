"""Rate-limiter coverage tests for the previously-unlimited public GET endpoints.

CLAUDE.md requires every public endpoint to enforce a rate limit — otherwise
an anonymous scraper can drive expensive DB queries (``COUNT(DISTINCT ...)``,
per-version metadata lookups, per-org profile fetches) cheaply from an
un-throttled path.

These tests wire the shared ``public_read_*`` limiter onto the endpoints via
the standard test app and assert that a burst past the configured ceiling
returns 429 — locking in the limiter on each endpoint against a future
refactor that drops the dependency.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(test_app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Rebuild the TestClient so every request gets a fresh source IP.

    ``TestClient`` uses ``127.0.0.1`` by default; since the RateLimiter keys
    on client IP, all requests share a bucket — which is exactly what we
    want when we're specifically testing that the bucket is enforced.
    """
    return TestClient(test_app)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/v1/stats"),
        ("get", "/v1/orgs/stats"),
        ("get", "/v1/orgs/profiles"),
    ],
)
class TestPublicReadEndpointsAreRateLimited:
    """Bursting past the configured ceiling on any of the previously-unlimited
    public read endpoints must return 429. Without this dependency they were
    happy to serve unlimited requests to any anonymous IP."""

    def test_burst_beyond_limit_returns_429(
        self,
        method: str,
        path: str,
        test_app: FastAPI,
        test_settings: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Shrink the limit so we don't need to fire 30 real requests
        test_settings.public_read_rate_limit = 3
        test_settings.public_read_rate_window = 60

        # Reset any cached RateLimiter that a previous parametric run may
        # have created against the app.state — otherwise the previous test's
        # limit sticks and this run gets 429 on request #1 or never.
        for attr in ("_public_read_rate_limiter",):
            if hasattr(test_app.state, attr):
                delattr(test_app.state, attr)

        # Stub the underlying DB helpers so a 200 is returned as long as the
        # limiter permits. We're testing the limiter, not the query.
        with (
            patch("decision_hub.api.registry_routes.fetch_registry_stats", return_value={"skills": 0}),
            patch("decision_hub.api.org_routes.fetch_org_stats", return_value=[]),
            patch("decision_hub.api.org_routes.list_all_org_profiles", return_value=[]),
        ):
            client = _make_client(test_app, monkeypatch)

            # Requests 1-3 succeed; the 4th trips the limiter.
            for _ in range(3):
                resp = getattr(client, method)(path)
                assert resp.status_code == 200, f"unexpected {resp.status_code} for {path}: {resp.text}"

            over = getattr(client, method)(path)
            assert over.status_code == 429, (
                f"{path} should return 429 once the public_read burst is exceeded, got {over.status_code}"
            )


class TestSkillSummaryEndpointRateLimited:
    """/v1/skills/{org}/{name}/summary was previously not rate-limited.

    Kept as a separate test class because the fixture path needs different
    DB stubs than the /stats endpoints above.
    """

    def test_summary_endpoint_enforces_burst_limit(
        self,
        test_app: FastAPI,
        test_settings: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from datetime import UTC, datetime
        from uuid import uuid4

        test_settings.public_read_rate_limit = 3
        test_settings.public_read_rate_window = 60
        for attr in ("_public_read_rate_limiter",):
            if hasattr(test_app.state, attr):
                delattr(test_app.state, attr)

        skill = MagicMock()
        skill.description = "d"
        skill.download_count = 0
        skill.category = "cat"
        skill.visibility = "public"
        skill.source_repo_url = None
        skill.manifest_path = None
        skill.source_repo_removed = False
        skill.github_stars = None
        skill.github_forks = None
        skill.github_watchers = None
        skill.github_is_archived = None
        skill.github_license = None
        version = MagicMock()
        version.semver = "1.0.0"
        version.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        version.eval_status = "passed"
        version.published_by = uuid4()

        with (
            patch("decision_hub.api.registry_routes.list_user_org_ids", return_value=None),
            patch("decision_hub.api.registry_routes.find_skill_by_slug", return_value=skill),
            patch("decision_hub.api.registry_routes.resolve_latest_version", return_value=version),
            patch("decision_hub.api.registry_routes.find_org_by_slug", return_value=None),
            patch("decision_hub.api.registry_routes.format_trust_score", return_value="A"),
            patch("decision_hub.api.registry_routes.resolve_author_display", return_value="alice"),
            patch("decision_hub.api.registry_routes.has_active_tracker_for_repo", return_value=False),
        ):
            client = _make_client(test_app, monkeypatch)
            for _ in range(3):
                resp = client.get("/v1/skills/acme/weather/summary")
                assert resp.status_code == 200, resp.text

            over = client.get("/v1/skills/acme/weather/summary")
            assert over.status_code == 429
