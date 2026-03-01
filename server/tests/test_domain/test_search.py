"""Tests for domain/search.py -- index building and trust scoring."""

from decision_hub.domain.search import (
    build_index_entry,
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


def test_serialize_index_includes_github_stars_and_forks():
    entries = [
        build_index_entry(
            "org1",
            "skill1",
            "Desc 1",
            "1.0.0",
            "passed",
            github_stars=150,
            github_forks=30,
        ),
        build_index_entry(
            "org2",
            "skill2",
            "Desc 2",
            "0.1.0",
            "pending",
            github_stars=None,
            github_forks=None,
        ),
    ]
    jsonl = serialize_index(entries)
    lines = jsonl.strip().split("\n")
    assert '"github_stars": 150' in lines[0]
    assert '"github_forks": 30' in lines[0]
    # Omitted when None
    assert "github_stars" not in lines[1]
    assert "github_forks" not in lines[1]


def test_serialize_index_includes_license():
    entries = [
        build_index_entry(
            "org1",
            "skill1",
            "Desc 1",
            "1.0.0",
            "passed",
            github_license="MIT",
        ),
        build_index_entry(
            "org2",
            "skill2",
            "Desc 2",
            "0.1.0",
            "pending",
            github_license=None,
        ),
    ]
    jsonl = serialize_index(entries)
    lines = jsonl.strip().split("\n")
    assert '"license": "MIT"' in lines[0]
    # Omitted when None
    assert "license" not in lines[1]


def test_serialize_empty():
    jsonl = serialize_index([])
    assert jsonl == ""
