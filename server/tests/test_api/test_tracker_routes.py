"""Integration tests for tracker CRUD API routes."""

from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from decision_hub.api.tracker_routes import router as tracker_router
from decision_hub.models import Organization, SkillTracker


@pytest.fixture
def tracker_app(test_app: FastAPI) -> FastAPI:
    """Test app with tracker routes included."""
    test_app.include_router(tracker_router)
    return test_app


@pytest.fixture
def tracker_client(tracker_app: FastAPI) -> TestClient:
    return TestClient(tracker_app)


def _make_tracker(
    user_id: UUID | None = None,
    org_slug: str = "test-org",
    repo_url: str = "https://github.com/owner/repo",
    branch: str = "main",
    tracker_id: UUID | None = None,
) -> SkillTracker:
    return SkillTracker(
        id=tracker_id or uuid4(),
        user_id=user_id or UUID("12345678-1234-5678-1234-567812345678"),
        org_slug=org_slug,
        repo_url=repo_url,
        branch=branch,
        last_commit_sha=None,
        poll_interval_minutes=60,
        enabled=True,
        last_checked_at=None,
        last_published_at=None,
        last_error=None,
        created_at=None,
    )


def _make_org(slug: str = "test-org") -> Organization:
    return Organization(id=uuid4(), slug=slug, owner_id=uuid4())


class TestCreateTracker:
    @patch("decision_hub.api.tracker_routes.check_repo_accessible", return_value=True)
    @patch("decision_hub.api.tracker_routes.list_user_orgs")
    @patch("decision_hub.api.tracker_routes.insert_skill_tracker")
    def test_create_tracker_success(
        self, mock_insert, mock_list_orgs, mock_accessible, tracker_client, auth_headers, sample_user_id
    ):
        org = _make_org()
        mock_list_orgs.return_value = [org]
        tracker = _make_tracker(user_id=sample_user_id)
        mock_insert.return_value = tracker

        resp = tracker_client.post(
            "/v1/trackers",
            headers=auth_headers,
            json={"repo_url": "https://github.com/owner/repo"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["repo_url"] == "https://github.com/owner/repo"
        assert data["branch"] == "main"
        assert data["warning"] is None

    @patch("decision_hub.api.tracker_routes.check_repo_accessible", return_value=False)
    @patch("decision_hub.api.tracker_routes.list_user_orgs")
    @patch("decision_hub.api.tracker_routes.insert_skill_tracker")
    def test_create_tracker_private_repo_warning(
        self, mock_insert, mock_list_orgs, mock_accessible, tracker_client, auth_headers, sample_user_id
    ):
        org = _make_org()
        mock_list_orgs.return_value = [org]
        tracker = _make_tracker(user_id=sample_user_id)
        mock_insert.return_value = tracker

        resp = tracker_client.post(
            "/v1/trackers",
            headers=auth_headers,
            json={"repo_url": "https://github.com/owner/private-repo"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["warning"] is not None
        assert "private" in data["warning"].lower()
        assert "GITHUB_TOKEN" in data["warning"]

    def test_create_tracker_invalid_url(self, tracker_client, auth_headers):
        resp = tracker_client.post(
            "/v1/trackers",
            headers=auth_headers,
            json={"repo_url": "https://gitlab.com/owner/repo"},
        )
        assert resp.status_code == 422

    def test_create_tracker_interval_too_low(self, tracker_client, auth_headers):
        resp = tracker_client.post(
            "/v1/trackers",
            headers=auth_headers,
            json={"repo_url": "https://github.com/owner/repo", "poll_interval_minutes": 3},
        )
        assert resp.status_code == 422

    @patch("decision_hub.api.tracker_routes.list_user_orgs")
    @patch("decision_hub.api.tracker_routes.insert_skill_tracker")
    def test_create_tracker_duplicate(self, mock_insert, mock_list_orgs, tracker_client, auth_headers):
        from sqlalchemy.exc import IntegrityError

        mock_list_orgs.return_value = [_make_org()]
        mock_insert.side_effect = IntegrityError("duplicate", {}, Exception())

        resp = tracker_client.post(
            "/v1/trackers",
            headers=auth_headers,
            json={"repo_url": "https://github.com/owner/repo"},
        )
        assert resp.status_code == 409


class TestListTrackers:
    @patch("decision_hub.api.tracker_routes.list_skill_trackers_for_user")
    def test_list_trackers_empty(self, mock_list, tracker_client, auth_headers):
        mock_list.return_value = []
        resp = tracker_client.get("/v1/trackers", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("decision_hub.api.tracker_routes.list_skill_trackers_for_user")
    def test_list_trackers_returns_user_trackers_only(self, mock_list, tracker_client, auth_headers, sample_user_id):
        tracker = _make_tracker(user_id=sample_user_id)
        mock_list.return_value = [tracker]
        resp = tracker_client.get("/v1/trackers", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["user_id"] == str(sample_user_id)


class TestGetTracker:
    @patch("decision_hub.api.tracker_routes.find_skill_tracker")
    def test_get_tracker_success(self, mock_find, tracker_client, auth_headers, sample_user_id):
        tracker = _make_tracker(user_id=sample_user_id)
        mock_find.return_value = tracker
        resp = tracker_client.get(f"/v1/trackers/{tracker.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == str(tracker.id)

    @patch("decision_hub.api.tracker_routes.find_skill_tracker")
    def test_get_tracker_not_found(self, mock_find, tracker_client, auth_headers):
        mock_find.return_value = None
        resp = tracker_client.get(f"/v1/trackers/{uuid4()}", headers=auth_headers)
        assert resp.status_code == 404

    @patch("decision_hub.api.tracker_routes.find_skill_tracker")
    def test_get_tracker_other_user(self, mock_find, tracker_client, auth_headers):
        other_user_id = uuid4()
        tracker = _make_tracker(user_id=other_user_id)
        mock_find.return_value = tracker
        resp = tracker_client.get(f"/v1/trackers/{tracker.id}", headers=auth_headers)
        assert resp.status_code == 404


class TestUpdateTracker:
    @patch("decision_hub.api.tracker_routes.find_skill_tracker")
    @patch("decision_hub.api.tracker_routes.update_skill_tracker")
    def test_update_tracker_pause(self, mock_update, mock_find, tracker_client, auth_headers, sample_user_id):
        tracker = _make_tracker(user_id=sample_user_id)
        paused_tracker = SkillTracker(
            id=tracker.id,
            user_id=tracker.user_id,
            org_slug=tracker.org_slug,
            repo_url=tracker.repo_url,
            branch=tracker.branch,
            last_commit_sha=tracker.last_commit_sha,
            poll_interval_minutes=tracker.poll_interval_minutes,
            enabled=False,
            last_checked_at=tracker.last_checked_at,
            last_published_at=tracker.last_published_at,
            last_error=tracker.last_error,
            created_at=tracker.created_at,
        )
        mock_find.side_effect = [tracker, paused_tracker]

        resp = tracker_client.patch(
            f"/v1/trackers/{tracker.id}",
            headers=auth_headers,
            json={"enabled": False},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    @patch("decision_hub.api.tracker_routes.find_skill_tracker")
    @patch("decision_hub.api.tracker_routes.update_skill_tracker")
    def test_update_tracker_resume(self, mock_update, mock_find, tracker_client, auth_headers, sample_user_id):
        tracker = _make_tracker(user_id=sample_user_id)
        resumed_tracker = SkillTracker(
            id=tracker.id,
            user_id=tracker.user_id,
            org_slug=tracker.org_slug,
            repo_url=tracker.repo_url,
            branch=tracker.branch,
            last_commit_sha=tracker.last_commit_sha,
            poll_interval_minutes=tracker.poll_interval_minutes,
            enabled=True,
            last_checked_at=tracker.last_checked_at,
            last_published_at=tracker.last_published_at,
            last_error=tracker.last_error,
            created_at=tracker.created_at,
        )
        mock_find.side_effect = [tracker, resumed_tracker]

        resp = tracker_client.patch(
            f"/v1/trackers/{tracker.id}",
            headers=auth_headers,
            json={"enabled": True},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    @patch("decision_hub.api.tracker_routes.find_skill_tracker")
    @patch("decision_hub.api.tracker_routes.update_skill_tracker")
    def test_update_tracker_interval(self, mock_update, mock_find, tracker_client, auth_headers, sample_user_id):
        tracker = _make_tracker(user_id=sample_user_id)
        updated_tracker = SkillTracker(
            id=tracker.id,
            user_id=tracker.user_id,
            org_slug=tracker.org_slug,
            repo_url=tracker.repo_url,
            branch=tracker.branch,
            last_commit_sha=tracker.last_commit_sha,
            poll_interval_minutes=30,
            enabled=tracker.enabled,
            last_checked_at=tracker.last_checked_at,
            last_published_at=tracker.last_published_at,
            last_error=tracker.last_error,
            created_at=tracker.created_at,
        )
        mock_find.side_effect = [tracker, updated_tracker]

        resp = tracker_client.patch(
            f"/v1/trackers/{tracker.id}",
            headers=auth_headers,
            json={"poll_interval_minutes": 30},
        )
        assert resp.status_code == 200
        assert resp.json()["poll_interval_minutes"] == 30


class TestDeleteTracker:
    @patch("decision_hub.api.tracker_routes.delete_skill_tracker")
    @patch("decision_hub.api.tracker_routes.find_skill_tracker")
    def test_delete_tracker_success(self, mock_find, mock_delete, tracker_client, auth_headers, sample_user_id):
        tracker = _make_tracker(user_id=sample_user_id)
        mock_find.return_value = tracker
        mock_delete.return_value = True

        resp = tracker_client.delete(f"/v1/trackers/{tracker.id}", headers=auth_headers)
        assert resp.status_code == 204

    @patch("decision_hub.api.tracker_routes.find_skill_tracker")
    def test_delete_tracker_not_found(self, mock_find, tracker_client, auth_headers):
        mock_find.return_value = None
        resp = tracker_client.delete(f"/v1/trackers/{uuid4()}", headers=auth_headers)
        assert resp.status_code == 404
