"""Server-side integration tests for manifest validation, search indexing, and
S3 key building using inline fixtures that mimic a docx-like skill.

These tests used to require a real skill directory at ~/.claude/skills/docx/.
They are now self-contained so they run in CI without external dependencies.
"""

from decision_hub.domain.gauntlet import check_manifest_schema
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


class TestStaticAnalysis:
    """Run manifest checks against inline docx-like skill content."""

    def test_check_manifest_schema_passes(self) -> None:
        result = check_manifest_schema(SKILL_MD_CONTENT)
        assert result.passed is True
        assert result.check_name == "manifest_schema"


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
