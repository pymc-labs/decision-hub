"""Tests for the row-to-response helpers shared across registry & search routes.

These helpers are the single source of truth for translating a DB row dict
(produced by ``_row_to_skill_summary`` / ``_SKILL_SUMMARY_COLUMNS``) into the
public API response shape. They exist to prevent the dual-write footgun
documented in CLAUDE.md, where adding a new column required updating
multiple call sites in lock-step.
"""

from datetime import UTC, datetime

from decision_hub.api.registry_routes import _format_summary_dt, _skill_summary_from_row
from decision_hub.api.search_routes import _ask_skill_ref_from_row

# ---------------------------------------------------------------------------
# _skill_summary_from_row
# ---------------------------------------------------------------------------


class TestSkillSummaryFromRow:
    """Tests for the row -> SkillSummary builder used by /v1/skills."""

    def _full_row(self) -> dict:
        return {
            "org_slug": "acme",
            "skill_name": "weather",
            "description": "Forecasting skill",
            "latest_version": "1.2.3",
            "created_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
            "eval_status": "passed",
            "published_by": "alice",
            "download_count": 42,
            "is_personal_org": False,
            "category": "Data Science",
            "visibility": "public",
            "source_repo_url": "https://github.com/acme/weather-skill",
            "manifest_path": "skills/weather/SKILL.md",
            "source_repo_removed": False,
            "github_stars": 12,
            "github_forks": 3,
            "github_watchers": 1,
            "github_is_archived": False,
            "github_license": "MIT",
        }

    def test_full_row_maps_every_field(self) -> None:
        row = self._full_row()
        summary = _skill_summary_from_row(row, is_auto_synced=True)

        assert summary.org_slug == "acme"
        assert summary.skill_name == "weather"
        assert summary.description == "Forecasting skill"
        assert summary.latest_version == "1.2.3"
        assert summary.updated_at == "2026-01-02 03:04:05"
        # passed -> A in the trust-score formatter
        assert summary.safety_rating == "A"
        assert summary.author == "alice"
        assert summary.download_count == 42
        assert summary.category == "Data Science"
        assert summary.visibility == "public"
        assert summary.source_repo_url == "https://github.com/acme/weather-skill"
        assert summary.manifest_path == "skills/weather/SKILL.md"
        assert summary.github_stars == 12
        assert summary.github_license == "MIT"
        assert summary.is_auto_synced is True

    def test_minimal_row_falls_back_to_defaults(self) -> None:
        """Missing optional columns must not raise -- defaults are used."""
        row = {
            "org_slug": "acme",
            "skill_name": "weather",
            "latest_version": "0.1.0",
        }
        summary = _skill_summary_from_row(row, is_auto_synced=False)

        assert summary.description == ""
        assert summary.updated_at == ""
        assert summary.author == ""
        assert summary.download_count == 0
        assert summary.category == ""
        assert summary.visibility == "public"
        assert summary.source_repo_url is None
        assert summary.github_stars is None
        assert summary.is_auto_synced is False

    def test_is_auto_synced_overrides_row(self) -> None:
        """The list endpoint passes the joined ``has_tracker`` value via this kwarg."""
        row = self._full_row()
        summary = _skill_summary_from_row(row, is_auto_synced=False)
        assert summary.is_auto_synced is False

    def test_format_summary_dt_handles_none(self) -> None:
        assert _format_summary_dt(None) == ""

    def test_null_text_columns_are_coerced(self) -> None:
        """Postgres can return NULL for text columns; coerce to empty string."""
        row = {
            "org_slug": "acme",
            "skill_name": "weather",
            "latest_version": "0.1.0",
            "description": None,
            "category": None,
        }
        summary = _skill_summary_from_row(row, is_auto_synced=False)
        assert summary.description == ""
        assert summary.category == ""


# ---------------------------------------------------------------------------
# _ask_skill_ref_from_row
# ---------------------------------------------------------------------------


class TestAskSkillRefFromRow:
    """Tests for the row -> AskSkillRef builder used by /v1/ask."""

    def _row(self) -> dict:
        return {
            "org_slug": "acme",
            "skill_name": "weather",
            "description": "Forecasting skill",
            "eval_status": "passed",
            "published_by": "alice",
            "category": "Data Science",
            "download_count": 7,
            "latest_version": "1.0.0",
            "source_repo_url": "https://github.com/acme/weather-skill",
            "gauntlet_summary": "All checks passed",
            "github_stars": 12,
            "github_license": "MIT",
        }

    def test_full_row_with_explicit_reason(self) -> None:
        ref = _ask_skill_ref_from_row(self._row(), reason="LLM-cited match")

        assert ref.org_slug == "acme"
        assert ref.skill_name == "weather"
        assert ref.description == "Forecasting skill"
        assert ref.safety_rating == "A"
        assert ref.author == "alice"
        assert ref.category == "Data Science"
        assert ref.download_count == 7
        assert ref.latest_version == "1.0.0"
        assert ref.source_repo_url == "https://github.com/acme/weather-skill"
        assert ref.gauntlet_summary == "All checks passed"
        assert ref.github_stars == 12
        assert ref.github_license == "MIT"
        assert ref.reason == "LLM-cited match"

    def test_minimal_row_uses_safe_defaults(self) -> None:
        row = {"org_slug": "acme", "skill_name": "weather"}
        ref = _ask_skill_ref_from_row(row, reason="Matched your search query.")
        assert ref.description == ""
        assert ref.author == ""
        assert ref.category == ""
        assert ref.download_count == 0
        assert ref.latest_version == ""
        assert ref.source_repo_url is None
        assert ref.gauntlet_summary is None
        assert ref.reason == "Matched your search query."

    def test_reason_is_required_kwarg(self) -> None:
        """The reason differs between paths (LLM-cited vs. fallback) and must be explicit."""
        import pytest

        with pytest.raises(TypeError):
            # type: ignore[call-arg] -- intentionally wrong signature
            _ask_skill_ref_from_row({"org_slug": "x", "skill_name": "y"})
