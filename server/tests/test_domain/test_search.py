"""Tests for domain/search.py -- index building and trust scoring."""

from decision_hub.domain.search import (
    build_index_entry,
    build_index_entry_from_row,
    format_trust_score,
    serialize_index,
)


def test_format_trust_score_passed():
    assert format_trust_score("passed") == "A"


def test_format_trust_score_pending():
    assert format_trust_score("pending") == "C"


def test_format_trust_score_failed():
    assert format_trust_score("failed") == "F"


def test_format_trust_score_unknown():
    assert format_trust_score("other") == "?"


def test_build_index_entry():
    entry = build_index_entry(
        org_slug="pymc",
        skill_name="causalpy",
        description="Bayesian causal inference",
        latest_version="1.4.2",
        eval_status="passed",
    )
    assert entry.org_slug == "pymc"
    assert entry.skill_name == "causalpy"
    assert entry.trust_score == "A"
    assert entry.download_count == 0
    assert entry.source_repo_url is None


def test_build_index_entry_with_metadata():
    entry = build_index_entry(
        org_slug="acme",
        skill_name="weather",
        description="Weather forecasting",
        latest_version="1.0.0",
        eval_status="passed",
        download_count=42,
        source_repo_url="https://github.com/acme/weather",
    )
    assert entry.download_count == 42
    assert entry.source_repo_url == "https://github.com/acme/weather"


def test_serialize_index():
    entries = [
        build_index_entry("org1", "skill1", "Desc 1", "1.0.0", "passed", download_count=10),
        build_index_entry(
            "org2",
            "skill2",
            "Desc 2",
            "0.1.0",
            "pending",
            source_repo_url="https://github.com/org2/skill2",
        ),
    ]
    jsonl = serialize_index(entries)

    lines = jsonl.strip().split("\n")
    assert len(lines) == 2
    assert "org1" in lines[0]
    assert '"downloads": 10' in lines[0]
    assert "source_repo_url" not in lines[0]  # omitted when None
    assert "org2" in lines[1]
    assert "https://github.com/org2/skill2" in lines[1]


def test_serialize_index_includes_github_metadata():
    entries = [
        build_index_entry(
            "org1",
            "skill1",
            "Desc 1",
            "1.0.0",
            "passed",
            github_stars=150,
            github_forks=30,
            github_license="MIT",
        ),
        build_index_entry(
            "org2",
            "skill2",
            "Desc 2",
            "0.1.0",
            "pending",
            github_stars=None,
            github_forks=None,
            github_license=None,
        ),
    ]
    jsonl = serialize_index(entries)
    lines = jsonl.strip().split("\n")
    assert '"github_stars": 150' in lines[0]
    assert '"github_forks": 30' in lines[0]
    assert '"license": "MIT"' in lines[0]
    # Omitted when None/empty
    assert "github_stars" not in lines[1]
    assert "github_forks" not in lines[1]
    assert "license" not in lines[1]


def test_serialize_empty():
    jsonl = serialize_index([])
    assert jsonl == ""


def test_build_index_entry_from_row_full():
    """Building from a complete row should populate every public field."""
    row = {
        "org_slug": "acme",
        "skill_name": "weather",
        "description": "Forecasting",
        "latest_version": "1.2.3",
        "eval_status": "passed",
        "published_by": "alice",
        "category": "analytics",
        "download_count": 17,
        "source_repo_url": "https://github.com/acme/weather",
        "gauntlet_summary": "no issues",
        "github_stars": 200,
        "github_forks": 5,
        "github_license": "MIT",
        "source_repo_removed": False,
        "github_is_archived": False,
    }
    entry = build_index_entry_from_row(row)
    assert entry.org_slug == "acme"
    assert entry.skill_name == "weather"
    assert entry.author == "alice"
    assert entry.category == "analytics"
    assert entry.download_count == 17
    assert entry.trust_score == "A"
    assert entry.source_status == "active"
    assert entry.github_stars == 200
    assert entry.github_forks == 5
    assert entry.github_license == "MIT"


def test_build_index_entry_from_row_handles_missing_fields():
    """Missing or None columns should not blow up the helper."""
    row = {
        "org_slug": "acme",
        "skill_name": "weather",
        "latest_version": "1.0.0",
        "eval_status": "pending",
        # description / category / download_count / etc. intentionally absent
    }
    entry = build_index_entry_from_row(row)
    assert entry.description == ""
    assert entry.category == ""
    assert entry.download_count == 0
    assert entry.author == ""
    assert entry.source_status == "active"


def test_build_index_entry_from_row_marks_tracker_author_as_auto_sync():
    """published_by = 'tracker:<uuid>' should resolve to the 'auto-sync' label."""
    row = {
        "org_slug": "acme",
        "skill_name": "weather",
        "latest_version": "1.0.0",
        "eval_status": "passed",
        "published_by": "tracker:00000000-0000-0000-0000-000000000000",
    }
    entry = build_index_entry_from_row(row)
    assert entry.author == "auto-sync"


def test_build_index_entry_from_row_marks_removed_source():
    row = {
        "org_slug": "acme",
        "skill_name": "weather",
        "latest_version": "1.0.0",
        "eval_status": "passed",
        "source_repo_removed": True,
    }
    entry = build_index_entry_from_row(row)
    assert entry.source_status == "removed"


def test_build_index_entry_from_row_marks_archived_source():
    row = {
        "org_slug": "acme",
        "skill_name": "weather",
        "latest_version": "1.0.0",
        "eval_status": "passed",
        "github_is_archived": True,
    }
    entry = build_index_entry_from_row(row)
    assert entry.source_status == "archived"
