"""Tests for domain/search.py -- index building and trust scoring."""

from decision_hub.domain.search import (
    build_index_entry,
    format_deterministic_results,
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


def test_serialize_index():
    entries = [
        build_index_entry("org1", "skill1", "Desc 1", "1.0.0", "passed"),
        build_index_entry("org2", "skill2", "Desc 2", "0.1.0", "pending"),
    ]
    jsonl = serialize_index(entries)

    lines = jsonl.strip().split("\n")
    assert len(lines) == 2
    assert "org1" in lines[0]
    assert "org2" in lines[1]


def test_serialize_empty():
    jsonl = serialize_index([])
    assert jsonl == ""


def test_format_deterministic_results():
    entries = [
        build_index_entry("org1", "skill1", "Desc 1", "1.0.0", "passed"),
        build_index_entry("org2", "skill2", "Desc 2", "0.1.0", "pending"),
    ]
    result = format_deterministic_results(entries)
    assert "1." in result
    assert "2." in result
    assert "org1/skill1" in result
    assert "org2/skill2" in result
    assert "v1.0.0" in result
    assert "v0.1.0" in result
    assert "[A]" in result
    assert "[C]" in result


def test_format_deterministic_results_empty():
    result = format_deterministic_results([])
    assert "No skills matched" in result
