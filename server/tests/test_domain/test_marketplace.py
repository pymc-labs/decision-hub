"""Tests for marketplace skill-to-plugin mapping."""

import json

from decision_hub.domain.marketplace import (
    SkillPluginEntry,
    build_marketplace_json,
    build_plugin_json,
    plugin_name_from_skill,
)


def test_plugin_name_from_skill():
    assert plugin_name_from_skill("pymc-labs", "bayesian-modeling") == "pymc-labs--bayesian-modeling"
    assert plugin_name_from_skill("alice", "hello") == "alice--hello"


def test_build_plugin_json():
    result = build_plugin_json(
        org_slug="pymc-labs",
        skill_name="bayesian-modeling",
        version="1.2.0",
        description="Bayesian stats",
        source_repo_url="https://github.com/pymc-labs/skills",
        category="data-science",
        gauntlet_grade="A",
        eval_status="passed",
    )
    parsed = json.loads(result)
    assert parsed["name"] == "pymc-labs--bayesian-modeling"
    assert parsed["version"] == "1.2.0"
    assert parsed["description"] == "Bayesian stats"
    assert parsed["author"]["name"] == "pymc-labs"
    assert parsed["repository"] == "https://github.com/pymc-labs/skills"
    assert "safety-grade-A" in parsed["keywords"]
    assert "evals-passing" in parsed["keywords"]


def test_build_plugin_json_no_repo_url():
    result = build_plugin_json(
        org_slug="alice",
        skill_name="hello",
        version="0.1.0",
        description="A greeting skill",
        source_repo_url=None,
        category="",
        gauntlet_grade="B",
        eval_status="pending",
    )
    parsed = json.loads(result)
    assert "repository" not in parsed
    assert "safety-grade-B" in parsed["keywords"]
    assert "evals-passing" not in parsed["keywords"]


def test_build_marketplace_json():
    entries = [
        SkillPluginEntry(
            org_slug="pymc-labs",
            skill_name="bayesian-modeling",
            version="1.2.0",
            description="Bayesian stats",
            category="data-science",
            gauntlet_grade="A",
            eval_status="passed",
            download_count=1200,
        ),
        SkillPluginEntry(
            org_slug="alice",
            skill_name="hello",
            version="0.1.0",
            description="Greeting",
            category="",
            gauntlet_grade="B",
            eval_status="pending",
            download_count=50,
        ),
    ]
    result = build_marketplace_json(entries)
    parsed = json.loads(result)
    assert parsed["name"] == "decision-hub"
    assert len(parsed["plugins"]) == 2
    first = parsed["plugins"][0]
    assert first["name"] == "pymc-labs--bayesian-modeling"
    assert first["source"] == "./plugins/pymc-labs--bayesian-modeling"
    assert first["version"] == "1.2.0"
    assert first["category"] == "data-science"
    assert "safety-A" in first["tags"]
