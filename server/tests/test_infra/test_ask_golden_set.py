"""Golden-set regression tests for ask_conversational.

Builds a 10-skill index across 4 categories, then runs 10 queries
(5 recommendation, 3 comparison, 2 edge cases) and asserts structural
validity, no hallucination, and loose relevance.

Marked @slow — skipped in CI, run manually with: pytest -m slow -v
"""

from __future__ import annotations

import re

import pytest
from slow_helpers import LatencyTracker, get_default_gemini_model, load_google_api_key, timed

from decision_hub.domain.search import build_index_entry, serialize_index
from decision_hub.infra.gemini import ask_conversational, create_gemini_client

# ---------------------------------------------------------------------------
# Index: 10 skills across 4 categories
# ---------------------------------------------------------------------------

_SKILLS = [
    # Data processing (3)
    build_index_entry(
        org_slug="dataco",
        skill_name="csv-transformer",
        description="High-performance CSV parsing, filtering, and transformation tool",
        latest_version="2.1.0",
        eval_status="A",
        category="data-processing",
        download_count=1200,
        github_stars=4500,
        github_forks=320,
        github_license="MIT",
    ),
    build_index_entry(
        org_slug="dataco",
        skill_name="json-flattener",
        description="Flatten nested JSON structures into tabular format",
        latest_version="1.3.0",
        eval_status="A",
        category="data-processing",
        download_count=800,
        github_stars=2100,
        github_forks=150,
        github_license="Apache-2.0",
    ),
    build_index_entry(
        org_slug="pipeline-labs",
        skill_name="data-validator",
        description="Schema validation and data quality checks for CSV, JSON, and Parquet",
        latest_version="3.0.0",
        eval_status="A",
        category="data-processing",
        download_count=3500,
        github_stars=7200,
        github_forks=540,
        github_license="MIT",
    ),
    # Code generation (2)
    build_index_entry(
        org_slug="webdev",
        skill_name="react-scaffolder",
        description="Generate React components with TypeScript, hooks, and tests",
        latest_version="1.0.0",
        eval_status="A",
        category="code-generation",
        download_count=600,
        github_stars=3100,
        github_forks=210,
        github_license="MIT",
    ),
    build_index_entry(
        org_slug="apigen",
        skill_name="openapi-generator",
        description="Generate REST API client/server code from OpenAPI specifications",
        latest_version="2.5.0",
        eval_status="A",
        category="code-generation",
        download_count=2000,
        github_stars=9500,
        github_forks=800,
        github_license="Apache-2.0",
    ),
    # Testing (3)
    build_index_entry(
        org_slug="testkit",
        skill_name="browser-tester",
        description="End-to-end browser testing with Playwright and visual regression",
        latest_version="4.2.0",
        eval_status="A",
        category="testing",
        download_count=4000,
        github_stars=11000,
        github_forks=900,
        github_license="MIT",
    ),
    build_index_entry(
        org_slug="testkit",
        skill_name="unit-mocker",
        description="Generate unit test mocks and fixtures for Python and TypeScript",
        latest_version="1.1.0",
        eval_status="B",
        category="testing",
        download_count=500,
        github_stars=1800,
        github_forks=90,
        github_license="MIT",
    ),
    build_index_entry(
        org_slug="qatools",
        skill_name="load-tester",
        description="HTTP load testing with configurable concurrency and reporting",
        latest_version="2.0.0",
        eval_status="A",
        category="testing",
        download_count=1500,
        github_stars=5200,
        github_forks=380,
        github_license="Apache-2.0",
    ),
    # DevOps (2)
    build_index_entry(
        org_slug="infraco",
        skill_name="k8s-deployer",
        description="Kubernetes deployment automation with rolling updates and rollback",
        latest_version="3.1.0",
        eval_status="A",
        category="devops",
        download_count=5000,
        github_stars=14000,
        github_forks=1200,
        github_license="Apache-2.0",
    ),
    build_index_entry(
        org_slug="infraco",
        skill_name="ci-pipeline",
        description="CI/CD pipeline generator for GitHub Actions, GitLab CI, and Jenkins",
        latest_version="1.4.0",
        eval_status="A",
        category="devops",
        download_count=2500,
        github_stars=6800,
        github_forks=450,
        github_license="MIT",
    ),
]

_SKILL_NAMES = {(s.org_slug, s.skill_name) for s in _SKILLS}
_INDEX = serialize_index(_SKILLS)


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _assert_valid_response(
    result: dict,
    expected_skills: list[tuple[str, str]] | None = None,
) -> None:
    """Validate structural correctness and optionally loose relevance.

    Args:
        result: Dict returned by ask_conversational.
        expected_skills: If given, assert at least 1 of these appears in top 3
            referenced skills. Each tuple is (org_slug, skill_name).
    """
    # Schema: answer must be a non-empty string
    assert "answer" in result
    assert isinstance(result["answer"], str)
    assert len(result["answer"].strip()) > 0

    # Schema: referenced_skills must be a list of dicts
    assert "referenced_skills" in result
    refs = result["referenced_skills"]
    assert isinstance(refs, list)

    for ref in refs:
        assert "org_slug" in ref
        assert "skill_name" in ref
        assert "reason" in ref

    # No hallucination: every referenced skill must exist in the index
    for ref in refs:
        key = (ref["org_slug"], ref["skill_name"])
        assert key in _SKILL_NAMES, f"Hallucinated skill {key} not in index. Known skills: {_SKILL_NAMES}"

    # Loose relevance: at least 1 expected skill in top 3
    if expected_skills and refs:
        top3 = {(r["org_slug"], r["skill_name"]) for r in refs[:3]}
        matched = top3 & set(expected_skills)
        assert matched, f"None of {expected_skills} found in top 3 refs: {top3}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestAskGoldenSet:
    """Golden-set regression tests for ask_conversational.

    Skipped automatically when no GOOGLE_API_KEY is available.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        api_key = load_google_api_key()
        if not api_key:
            pytest.skip("GOOGLE_API_KEY not available")
        self.client = create_gemini_client(api_key)
        self.model = get_default_gemini_model()
        self.latency = LatencyTracker("ask_conversational", soft_p95_limit=15.0)
        yield
        print(self.latency.summary())

    # -- Recommendation queries (single domain) --

    def test_recommend_csv_processing(self):
        with timed(self.latency):
            result = ask_conversational(
                self.client, "I need a tool for CSV processing and transformation", _INDEX, self.model
            )
        _assert_valid_response(result, expected_skills=[("dataco", "csv-transformer")])

    def test_recommend_react_components(self):
        with timed(self.latency):
            result = ask_conversational(
                self.client, "recommend a skill for generating React components", _INDEX, self.model
            )
        _assert_valid_response(result, expected_skills=[("webdev", "react-scaffolder")])

    def test_recommend_browser_testing(self):
        with timed(self.latency):
            result = ask_conversational(
                self.client, "what's the best tool for browser end-to-end testing?", _INDEX, self.model
            )
        _assert_valid_response(result, expected_skills=[("testkit", "browser-tester")])

    def test_recommend_k8s_deployment(self):
        with timed(self.latency):
            result = ask_conversational(self.client, "I need help deploying to Kubernetes", _INDEX, self.model)
        _assert_valid_response(result, expected_skills=[("infraco", "k8s-deployer")])

    def test_recommend_api_generation(self):
        with timed(self.latency):
            result = ask_conversational(self.client, "generate API code from an OpenAPI spec", _INDEX, self.model)
        _assert_valid_response(result, expected_skills=[("apigen", "openapi-generator")])

    # -- Comparison queries (head-to-head) --

    def test_compare_data_tools(self):
        with timed(self.latency):
            result = ask_conversational(
                self.client,
                "compare dataco/csv-transformer and pipeline-labs/data-validator",
                _INDEX,
                self.model,
            )
        _assert_valid_response(result)
        # Comparison should mention numeric data
        assert re.search(r"\d[\d,]*\s*(?:stars?|downloads?)", result["answer"], re.IGNORECASE), (
            f"Comparison should mention stars or downloads.\nAnswer:\n{result['answer']}"
        )

    def test_compare_testing_tools(self):
        with timed(self.latency):
            result = ask_conversational(
                self.client,
                "compare testkit/browser-tester and qatools/load-tester for my QA workflow",
                _INDEX,
                self.model,
            )
        _assert_valid_response(result)
        assert re.search(r"\d[\d,]*\s*(?:stars?|downloads?)", result["answer"], re.IGNORECASE), (
            f"Comparison should mention numeric data.\nAnswer:\n{result['answer']}"
        )

    def test_compare_devops_tools(self):
        with timed(self.latency):
            result = ask_conversational(
                self.client,
                "which is better, infraco/k8s-deployer or infraco/ci-pipeline?",
                _INDEX,
                self.model,
            )
        _assert_valid_response(result)

    # -- Edge cases --

    def test_vague_query(self):
        """Very vague query should still return a valid response."""
        with timed(self.latency):
            result = ask_conversational(self.client, "help me with my project", _INDEX, self.model)
        _assert_valid_response(result)

    def test_very_specific_query(self):
        """Highly specific query should match the right tool."""
        with timed(self.latency):
            result = ask_conversational(
                self.client,
                "I need to validate Parquet files against a JSON schema and produce a data quality report",
                _INDEX,
                self.model,
            )
        _assert_valid_response(
            result,
            expected_skills=[("pipeline-labs", "data-validator")],
        )
