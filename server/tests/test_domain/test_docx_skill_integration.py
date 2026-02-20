"""Server-side integration tests for the Gauntlet pipeline, search indexing, and
S3 key building using inline fixtures that mimic a docx-like skill.

These tests used to require a real skill directory at ~/.claude/skills/docx/.
They are now self-contained so they run in CI without external dependencies.
"""

from decision_hub.domain.gauntlet import (
    check_manifest_schema,
    check_safety_scan,
    run_static_checks,
)
from decision_hub.domain.publish import build_s3_key
from decision_hub.domain.search import build_index_entry

# ---------------------------------------------------------------------------
# Inline fixtures — mimic a docx-like skill with subprocess usage
# ---------------------------------------------------------------------------

SKILL_MD_CONTENT = """\
---
name: docx
description: Create, edit, and analyze Word documents
---

You are a document processing assistant that helps users create, edit, and
analyze Microsoft Word (.docx) files.
"""

# Simulated Python source files with subprocess usage (like a real docx skill)
SOURCE_FILES: list[tuple[str, str]] = [
    (
        "pack.py",
        """\
import subprocess

def pack_document(source_dir: str, output_path: str) -> None:
    subprocess.run(["zip", "-r", output_path, source_dir], check=True)
""",
    ),
    (
        "redlining.py",
        """\
import subprocess

def compare_documents(old_path: str, new_path: str) -> str:
    result = subprocess.run(
        ["diff", old_path, new_path],
        capture_output=True, text=True,
    )
    return result.stdout
""",
    ),
    (
        "utils.py",
        """\
from pathlib import Path

def ensure_docx_extension(filename: str) -> str:
    if not filename.endswith(".docx"):
        return filename + ".docx"
    return filename
""",
    ),
]


class TestStaticAnalysis:
    """Run gauntlet checks against inline docx-like skill content."""

    def test_check_manifest_schema_passes(self) -> None:
        result = check_manifest_schema(SKILL_MD_CONTENT)
        assert result.passed is True
        assert result.check_name == "manifest_schema"

    def test_regex_prefilter_finds_subprocess(self) -> None:
        """Regex pre-filter should flag subprocess in pack.py and redlining.py
        when no LLM judge is provided (strict mode)."""
        result = check_safety_scan(SOURCE_FILES)
        assert result.passed is False
        assert "subprocess" in result.message

    def test_regex_prefilter_identifies_correct_files(self) -> None:
        result = check_safety_scan(SOURCE_FILES)
        assert "pack.py" in result.message
        assert "redlining.py" in result.message

    def test_llm_judge_approves_docx_subprocess(self) -> None:
        """When an LLM judge recognises subprocess as legitimate for a
        document processing skill, the safety scan should pass."""

        def approve_all(snippets, source_files, name, desc):
            return [{**s, "dangerous": False, "reason": f"Legitimate for {name}: {desc[:40]}"} for s in snippets]

        result = check_safety_scan(
            SOURCE_FILES,
            skill_name="docx",
            skill_description="Document creation, editing, and analysis",
            analyze_fn=approve_all,
        )
        assert result.passed is True
        assert "accepted" in result.message

    def test_run_static_checks_with_llm_passes(self) -> None:
        """Full Gauntlet with an LLM judge should pass the docx skill."""

        def approve_all(snippets, source_files, name, desc):
            return [{**s, "dangerous": False, "reason": "legitimate"} for s in snippets]

        report = run_static_checks(
            SKILL_MD_CONTENT,
            None,
            SOURCE_FILES,
            skill_name="docx",
            skill_description="Document creation and editing",
            analyze_fn=approve_all,
        )
        assert report.passed is True

    def test_run_static_checks_no_lockfile(self) -> None:
        """run_static_checks with no lockfile should produce a report
        with manifest_schema and safety_scan results."""
        report = run_static_checks(SKILL_MD_CONTENT, None, SOURCE_FILES)
        check_names = [r.check_name for r in report.results]
        assert "manifest_schema" in check_names
        assert "safety_scan" in check_names
        assert "dependency_audit" not in check_names

    def test_run_static_checks_strict_mode_fails(self) -> None:
        """Without an LLM judge, the docx skill fails due to subprocess."""
        report = run_static_checks(SKILL_MD_CONTENT, None, SOURCE_FILES)
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
        description = "Create, edit, and analyze Word documents"
        entry = build_index_entry(
            org_slug="example-org",
            skill_name="docx",
            description=description,
            latest_version="1.0.0",
            eval_status="passed",
        )
        assert entry.org_slug == "example-org"
        assert entry.skill_name == "docx"
        assert entry.description == description
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
