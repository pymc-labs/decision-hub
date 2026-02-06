"""Server-side integration tests using the real docx skill at ~/.claude/skills/docx/.

These tests validate the server domain layer against a real-world
skill directory, ensuring that static analysis, search indexing, and
S3 key building work correctly with production-like content.
"""

from pathlib import Path

import pytest

from decision_hub.domain.skill_manifest import parse_skill_md
from decision_hub.domain.publish import build_s3_key
from decision_hub.domain.evals import (
    check_manifest_schema,
    check_safety_scan,
    run_static_checks,
)
from decision_hub.domain.search import build_index_entry


DOCX_SKILL_PATH = Path.home() / ".claude" / "skills" / "docx"

# Guard: skip all tests if the docx skill is not installed locally
pytestmark = pytest.mark.skipif(
    not (DOCX_SKILL_PATH / "SKILL.md").exists(),
    reason="docx skill not found at ~/.claude/skills/docx",
)


def _collect_python_sources() -> list[tuple[str, str]]:
    """Collect all Python source files from the docx skill directory."""
    sources = []
    for py_file in sorted(DOCX_SKILL_PATH.rglob("*.py")):
        relative = py_file.relative_to(DOCX_SKILL_PATH)
        sources.append((str(relative), py_file.read_text()))
    return sources


class TestStaticAnalysis:
    """Run evals.py checks against real docx content."""

    def test_check_manifest_schema_passes(self) -> None:
        content = (DOCX_SKILL_PATH / "SKILL.md").read_text()
        result = check_manifest_schema(content)
        assert result.passed is True
        assert result.check_name == "manifest_schema"

    def test_regex_prefilter_finds_subprocess(self) -> None:
        """Regex pre-filter should flag subprocess in pack.py and redlining.py
        when no LLM judge is provided (strict mode)."""
        source_files = _collect_python_sources()
        result = check_safety_scan(source_files)
        assert result.passed is False
        assert "subprocess" in result.message

    def test_regex_prefilter_identifies_correct_files(self) -> None:
        source_files = _collect_python_sources()
        result = check_safety_scan(source_files)
        assert "pack.py" in result.message
        assert "redlining.py" in result.message

    def test_llm_judge_approves_docx_subprocess(self) -> None:
        """When an LLM judge recognises subprocess as legitimate for a
        document processing skill, the safety scan should pass."""
        def approve_all(snippets, name, desc):
            return [
                {**s, "dangerous": False,
                 "reason": f"Legitimate for {name}: {desc[:40]}"}
                for s in snippets
            ]

        source_files = _collect_python_sources()
        result = check_safety_scan(
            source_files,
            skill_name="docx",
            skill_description="Document creation, editing, and analysis",
            analyze_fn=approve_all,
        )
        assert result.passed is True
        assert "accepted" in result.message

    def test_run_static_checks_with_llm_passes(self) -> None:
        """Full Gauntlet with an LLM judge should pass the docx skill."""
        def approve_all(snippets, name, desc):
            return [
                {**s, "dangerous": False, "reason": "legitimate"}
                for s in snippets
            ]

        skill_md_content = (DOCX_SKILL_PATH / "SKILL.md").read_text()
        source_files = _collect_python_sources()
        report = run_static_checks(
            skill_md_content, None, source_files,
            skill_name="docx",
            skill_description="Document creation and editing",
            analyze_fn=approve_all,
        )
        assert report.passed is True

    def test_run_static_checks_no_lockfile(self) -> None:
        """run_static_checks with no lockfile should produce a report
        with manifest_schema and safety_scan results."""
        skill_md_content = (DOCX_SKILL_PATH / "SKILL.md").read_text()
        source_files = _collect_python_sources()
        report = run_static_checks(skill_md_content, None, source_files)
        check_names = [r.check_name for r in report.results]
        assert "manifest_schema" in check_names
        assert "safety_scan" in check_names
        assert "dependency_audit" not in check_names

    def test_run_static_checks_strict_mode_fails(self) -> None:
        """Without an LLM judge, the docx skill fails due to subprocess."""
        skill_md_content = (DOCX_SKILL_PATH / "SKILL.md").read_text()
        source_files = _collect_python_sources()
        report = run_static_checks(skill_md_content, None, source_files)
        assert report.passed is False


class TestS3KeyBuilding:
    """Verify S3 key format for published skills."""

    def test_build_s3_key_format(self) -> None:
        key = build_s3_key("example-org", "docx", "1.0.0")
        assert key == "skills/example-org/docx/1.0.0.zip"

    def test_build_s3_key_with_different_version(self) -> None:
        key = build_s3_key("example-org", "docx", "2.3.1")
        assert key == "skills/example-org/docx/2.3.1.zip"


class TestSearchIndexEntry:
    """Build index entries for docx skill."""

    def test_build_index_entry_fields(self) -> None:
        manifest = parse_skill_md(DOCX_SKILL_PATH / "SKILL.md")
        entry = build_index_entry(
            org_slug="example-org",
            skill_name="docx",
            description=manifest.description,
            latest_version="1.0.0",
            eval_status="passed",
        )
        assert entry.org_slug == "example-org"
        assert entry.skill_name == "docx"
        assert entry.description == manifest.description
        assert entry.latest_version == "1.0.0"
        assert entry.eval_status == "passed"
        assert entry.trust_score == "A"

    def test_build_index_entry_pending_status(self) -> None:
        entry = build_index_entry(
            org_slug="example-org",
            skill_name="docx",
            description="test",
            latest_version="0.1.0",
            eval_status="pending",
        )
        assert entry.trust_score == "C"
