"""Regression tests for ask_conversational markdown formatting.

These tests hit the real Gemini API to verify the LLM produces properly
formatted markdown (newlines, bullet lists, bold data points).
Marked @slow — skipped in CI, run manually with: pytest -m slow -v
"""

import os
import re
from pathlib import Path

import pytest

from decision_hub.domain.search import build_index_entry, serialize_index
from decision_hub.infra.gemini import ask_conversational, create_gemini_client


def _load_google_api_key() -> str | None:
    """Try to load GOOGLE_API_KEY from environment or server/.env files."""
    key = os.environ.get("GOOGLE_API_KEY", "")
    if key:
        return key

    for env_file in (".env.dev", ".env.prod"):
        path = Path(__file__).resolve().parents[2] / env_file
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line.startswith("GOOGLE_API_KEY="):
                    val = line.split("=", 1)[1].strip().strip("\"'")
                    if val:
                        return val
    return None


def _build_comparison_index() -> str:
    """Build a small JSONL index with two skills that have different metadata."""
    entries = [
        build_index_entry(
            org_slug="acme",
            skill_name="focused-tool",
            description="A specialized tool for one specific task",
            latest_version="1.0.0",
            eval_status="A",
            download_count=5,
            github_stars=120,
            github_forks=15,
            github_license="MIT",
        ),
        build_index_entry(
            org_slug="bigcorp",
            skill_name="general-tool",
            description="A general-purpose tool covering many tasks",
            latest_version="2.3.0",
            eval_status="A",
            download_count=500,
            github_stars=8500,
            github_forks=1200,
            github_license="Apache-2.0",
        ),
    ]
    return serialize_index(entries)


@pytest.mark.slow
class TestAskMarkdownFormatting:
    """Regression tests verifying ask responses use proper markdown.

    Skipped automatically when no GOOGLE_API_KEY is available.
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        api_key = _load_google_api_key()
        if not api_key:
            pytest.skip("GOOGLE_API_KEY not available")
        self.client = create_gemini_client(api_key)
        self.model = "gemini-2.5-flash"
        self.index = _build_comparison_index()

    def test_comparison_has_bullet_list_with_newlines(self):
        """Head-to-head comparison should produce markdown with proper newlines
        so bullet lists render correctly (not all on one line)."""
        result = ask_conversational(
            self.client,
            query="compare acme/focused-tool and bigcorp/general-tool",
            index=self.index,
            model=self.model,
        )
        answer = result["answer"]

        # Must contain newline-separated lines (not a single blob)
        lines = answer.strip().split("\n")
        assert len(lines) >= 5, (
            f"Expected at least 5 lines for a structured comparison, got {len(lines)}.\nAnswer:\n{answer}"
        )

        # Must contain markdown bullet points (- item) on their own lines
        bullet_lines = [line for line in lines if re.match(r"\s*-\s", line)]
        assert len(bullet_lines) >= 2, (
            f"Expected at least 2 bullet points, found {len(bullet_lines)}.\nAnswer:\n{answer}"
        )

    def test_comparison_has_bold_data_points(self):
        """Factual data points (stars, downloads, etc.) should be bolded."""
        result = ask_conversational(
            self.client,
            query="compare acme/focused-tool and bigcorp/general-tool",
            index=self.index,
            model=self.model,
        )
        answer = result["answer"]

        bold_matches = re.findall(r"\*\*[^*]+\*\*", answer)
        assert len(bold_matches) >= 2, (
            f"Expected at least 2 bold data points, found {len(bold_matches)}: {bold_matches}.\nAnswer:\n{answer}"
        )

    def test_recommendation_surfaces_stars_and_downloads(self):
        """When skills have significantly different stars/downloads,
        the response should mention the actual numbers."""
        result = ask_conversational(
            self.client,
            query="compare acme/focused-tool and bigcorp/general-tool",
            index=self.index,
            model=self.model,
        )
        answer = result["answer"]

        # Should mention star counts (8500 or 8.5k)
        has_big_stars = bool(re.search(r"8[.,]?5\s*k|8500", answer, re.IGNORECASE))
        assert has_big_stars, f"Expected response to mention bigcorp's ~8500 stars.\nAnswer:\n{answer}"

    def test_general_recommendation_has_proper_list_formatting(self):
        """Non-comparison queries should also produce well-formatted lists."""
        result = ask_conversational(
            self.client,
            query="recommend a tool for data processing",
            index=self.index,
            model=self.model,
        )
        answer = result["answer"]

        # Should have multiple lines, not a single blob of text
        lines = answer.strip().split("\n")
        non_empty = [line for line in lines if line.strip()]
        assert len(non_empty) >= 2, (
            f"Expected multi-line response, got {len(non_empty)} non-empty lines.\nAnswer:\n{answer}"
        )
