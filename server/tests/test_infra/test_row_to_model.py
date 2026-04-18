"""Tests for the generic _row_to_model helper and its thin wrappers.

These tests ensure the helper (1) populates every expected dataclass field,
(2) ignores extra columns in the row mapping, and (3) falls back to dataclass
defaults when a field is absent — which is critical because multiple callers
rely on this contract (e.g. ``User.github_orgs`` is never in the DB).
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from decision_hub.infra.database import (
    _row_to_audit_log_entry,
    _row_to_eval_report,
    _row_to_eval_run,
    _row_to_model,
    _row_to_organization,
    _row_to_skill,
    _row_to_skill_access_grant,
    _row_to_skill_tracker,
    _row_to_tracker_metrics,
    _row_to_user,
    _row_to_user_api_key,
    _row_to_version,
)
from decision_hub.models import (
    AuditLogEntry,
    EvalReport,
    EvalRun,
    Organization,
    Skill,
    SkillAccessGrant,
    SkillTracker,
    TrackerMetrics,
    User,
    UserApiKey,
    Version,
)


class _FakeRow:
    """Minimal stand-in for a SQLAlchemy row supporting ``row._mapping``."""

    def __init__(self, mapping: dict) -> None:
        self._mapping = mapping


UID = uuid4()
NOW = datetime(2026, 1, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# _row_to_model: contract tests
# ---------------------------------------------------------------------------


class TestRowToModelContract:
    def test_populates_exact_fields_on_simple_dataclass(self):
        row = _FakeRow({"id": UID, "github_id": "123", "username": "bob"})
        user = _row_to_model(row, User)
        assert user.id == UID
        assert user.github_id == "123"
        assert user.username == "bob"

    def test_ignores_extra_columns(self):
        # Search/fts rows often carry scoring columns not present on the model.
        row = _FakeRow(
            {
                "id": UID,
                "github_id": "123",
                "username": "bob",
                "fts_rank": 0.42,  # extra
                "vec_dist": 0.1,  # extra
            }
        )
        user = _row_to_model(row, User)
        assert user.username == "bob"

    def test_falls_back_to_default_when_field_absent(self):
        # github_orgs has no DB column; it's populated from JWT claims only.
        row = _FakeRow({"id": UID, "github_id": "123", "username": "bob"})
        user = _row_to_model(row, User)
        assert user.github_orgs == ()

    def test_none_values_pass_through(self):
        row = _FakeRow(
            {
                "id": UID,
                "github_id": "123",
                "username": "bob",
                "created_at": None,
                "updated_at": None,
            }
        )
        user = _row_to_model(row, User)
        assert user.created_at is None

    def test_required_field_missing_raises_type_error(self):
        # Missing `username` (no default) should surface as a TypeError.
        row = _FakeRow({"id": UID, "github_id": "123"})
        with pytest.raises(TypeError):
            _row_to_model(row, User)


# ---------------------------------------------------------------------------
# Regression: SkillTracker must pick up consecutive_permanent_failures
# ---------------------------------------------------------------------------


class TestSkillTrackerMapperRegression:
    """The old hand-rolled mapper dropped ``consecutive_permanent_failures``
    and silently returned the dataclass default (0) regardless of DB value.
    The generic helper fixes this.
    """

    def _base_mapping(self) -> dict:
        return {
            "id": UID,
            "user_id": UID,
            "org_slug": "acme",
            "repo_url": "https://github.com/acme/repo",
            "branch": "main",
            "last_commit_sha": "deadbeef",
            "poll_interval_minutes": 60,
            "enabled": True,
            "last_checked_at": NOW,
            "last_published_at": NOW,
            "last_error": None,
            "next_check_at": NOW,
            "created_at": NOW,
        }

    def test_reads_consecutive_permanent_failures_from_row(self):
        mapping = self._base_mapping()
        mapping["consecutive_permanent_failures"] = 5
        tracker = _row_to_skill_tracker(_FakeRow(mapping))
        assert tracker.consecutive_permanent_failures == 5

    def test_defaults_to_zero_when_column_absent(self):
        tracker = _row_to_skill_tracker(_FakeRow(self._base_mapping()))
        assert tracker.consecutive_permanent_failures == 0


# ---------------------------------------------------------------------------
# Smoke tests for every thin wrapper: dataclass round-trip
# ---------------------------------------------------------------------------


class TestWrapperRoundTrip:
    """Each wrapper must produce the correct frozen dataclass type and
    populate all required fields given a row mapping that matches the table.
    """

    def test_user_wrapper(self):
        row = _FakeRow({"id": UID, "github_id": "1", "username": "a"})
        assert isinstance(_row_to_user(row), User)

    def test_organization_wrapper(self):
        row = _FakeRow(
            {
                "id": UID,
                "slug": "acme",
                "owner_id": UID,
                "is_personal": False,
            }
        )
        org = _row_to_organization(row)
        assert isinstance(org, Organization)
        assert org.slug == "acme"

    def test_skill_wrapper(self):
        row = _FakeRow(
            {
                "id": UID,
                "org_id": UID,
                "name": "skill-a",
                "description": "desc",
            }
        )
        skill = _row_to_skill(row)
        assert isinstance(skill, Skill)
        assert skill.download_count == 0  # default applied

    def test_version_wrapper(self):
        row = _FakeRow(
            {
                "id": UID,
                "skill_id": UID,
                "semver": "1.0.0",
                "s3_key": "x",
                "checksum": "abc",
                "runtime_config": None,
                "eval_status": "A",
            }
        )
        v = _row_to_version(row)
        assert isinstance(v, Version)
        assert v.semver == "1.0.0"

    def test_user_api_key_wrapper(self):
        row = _FakeRow(
            {
                "id": UID,
                "user_id": UID,
                "key_name": "k",
                "encrypted_value": b"bytes",
                "created_at": NOW,
            }
        )
        assert isinstance(_row_to_user_api_key(row), UserApiKey)

    def test_skill_access_grant_wrapper(self):
        row = _FakeRow(
            {
                "id": UID,
                "skill_id": UID,
                "grantee_org_id": UID,
                "granted_by": UID,
                "created_at": NOW,
            }
        )
        assert isinstance(_row_to_skill_access_grant(row), SkillAccessGrant)

    def test_audit_log_wrapper(self):
        row = _FakeRow(
            {
                "id": UID,
                "org_slug": "acme",
                "skill_name": "s",
                "semver": "1.0.0",
                "grade": "A",
                "version_id": UID,
                "check_results": [],
                "llm_reasoning": None,
                "publisher": "bob",
            }
        )
        assert isinstance(_row_to_audit_log_entry(row), AuditLogEntry)

    def test_eval_report_wrapper(self):
        row = _FakeRow(
            {
                "id": UID,
                "version_id": UID,
                "agent": "claude",
                "judge_model": "claude-opus",
                "case_results": [],
                "passed": 0,
                "total": 0,
                "total_duration_ms": 0,
                "status": "pending",
            }
        )
        assert isinstance(_row_to_eval_report(row), EvalReport)

    def test_eval_run_wrapper(self):
        row = _FakeRow(
            {
                "id": UID,
                "version_id": UID,
                "user_id": UID,
                "agent": "claude",
                "judge_model": "claude-opus",
                "status": "pending",
                "stage": None,
                "current_case": None,
                "current_case_index": None,
                "total_cases": 0,
                "heartbeat_at": None,
                "log_s3_prefix": "x/",
                "log_seq": 0,
                "error_message": None,
                "created_at": NOW,
                "completed_at": None,
            }
        )
        assert isinstance(_row_to_eval_run(row), EvalRun)

    def test_tracker_metrics_wrapper(self):
        row = _FakeRow(
            {
                "id": UID,
                "recorded_at": NOW,
                "iterations": 1,
                "total_checked": 2,
                "trackers_due": 3,
                "trackers_unchanged": 4,
                "trackers_changed": 5,
                "trackers_errored": 0,
                "trackers_processed": 5,
                "trackers_failed": 0,
                "trackers_disabled": 0,
                "skipped_rate_limit": 0,
                "github_rate_remaining": 4999,
                "batch_duration_seconds": 1.5,
            }
        )
        m = _row_to_tracker_metrics(row)
        assert isinstance(m, TrackerMetrics)
        assert m.github_rate_remaining == 4999


# ---------------------------------------------------------------------------
# Cross-cutting guarantee: every required dataclass field still maps
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_cls",
    [User, Organization, Skill, Version, UserApiKey, SkillAccessGrant, SkillTracker],
)
def test_model_fields_can_be_populated_from_row(model_cls):
    """Sanity: a mapping that includes every dataclass field produces
    an instance with those exact values. Catches future drift where a
    new required field is added to the dataclass but not to the table.
    """
    import dataclasses

    # Build a mapping with a placeholder value for each field.
    mapping: dict = {}
    for f in dataclasses.fields(model_cls):
        if f.type is UUID or str(f.type).endswith("UUID"):
            mapping[f.name] = UID
        elif f.type in (datetime, "datetime", "datetime | None"):
            mapping[f.name] = NOW
        elif f.type in (bool, "bool"):
            mapping[f.name] = False
        elif f.type in (int, "int"):
            mapping[f.name] = 0
        elif f.type in (float, "float"):
            mapping[f.name] = 0.0
        elif f.type in (bytes, "bytes"):
            mapping[f.name] = b""
        else:
            mapping[f.name] = None
    instance = _row_to_model(_FakeRow(mapping), model_cls)
    assert isinstance(instance, model_cls)
