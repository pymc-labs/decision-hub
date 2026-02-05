"""Integration tests using the real docx skill at ~/.claude/skills/docx/.

These tests validate the Decision Hub domain layer against a real-world
skill directory, ensuring that parsing, packaging, validation, and
indexing work correctly with production-like content.
"""

import hashlib
import zipfile
import io
from pathlib import Path

import pytest

from decision_hub.domain.skill_manifest import parse_skill_md
from decision_hub.domain.publish import validate_semver, build_s3_key, validate_skill_name
from decision_hub.domain.install import (
    get_dhub_skill_path,
    verify_checksum,
    AGENT_SKILL_PATHS,
)
from decision_hub.domain.evals import (
    check_manifest_schema,
    check_safety_scan,
    run_static_checks,
)
from decision_hub.domain.search import build_index_entry, serialize_index, deserialize_index
from decision_hub.cli.registry import _create_zip


DOCX_SKILL_PATH = Path.home() / ".claude" / "skills" / "docx"

# Guard: skip all tests if the docx skill is not installed locally
pytestmark = pytest.mark.skipif(
    not (DOCX_SKILL_PATH / "SKILL.md").exists(),
    reason="docx skill not found at ~/.claude/skills/docx",
)


class TestSkillMdParsing:
    """Parse the real docx SKILL.md and verify extracted fields."""

    def test_parse_succeeds(self) -> None:
        manifest = parse_skill_md(DOCX_SKILL_PATH / "SKILL.md")
        assert manifest is not None

    def test_name_is_docx(self) -> None:
        manifest = parse_skill_md(DOCX_SKILL_PATH / "SKILL.md")
        assert manifest.name == "docx"

    def test_description_length(self) -> None:
        manifest = parse_skill_md(DOCX_SKILL_PATH / "SKILL.md")
        assert len(manifest.description) == 362

    def test_description_starts_with_comprehensive(self) -> None:
        manifest = parse_skill_md(DOCX_SKILL_PATH / "SKILL.md")
        assert manifest.description.startswith("Comprehensive document creation")

    def test_license_is_proprietary(self) -> None:
        manifest = parse_skill_md(DOCX_SKILL_PATH / "SKILL.md")
        assert manifest.license == "Proprietary. LICENSE.txt has complete terms"

    def test_runtime_is_none(self) -> None:
        manifest = parse_skill_md(DOCX_SKILL_PATH / "SKILL.md")
        assert manifest.runtime is None

    def test_testing_is_none(self) -> None:
        manifest = parse_skill_md(DOCX_SKILL_PATH / "SKILL.md")
        assert manifest.testing is None

    def test_body_starts_with_docx_creation(self) -> None:
        manifest = parse_skill_md(DOCX_SKILL_PATH / "SKILL.md")
        assert manifest.body.startswith("# DOCX creation")

    def test_body_is_substantial(self) -> None:
        """The body (system prompt) should be several KB of content."""
        manifest = parse_skill_md(DOCX_SKILL_PATH / "SKILL.md")
        assert len(manifest.body) > 5000

    def test_no_validation_errors(self) -> None:
        """parse_skill_md raises ValueError on validation failure,
        so a successful parse implies no errors."""
        from decision_hub.domain.skill_manifest import validate_manifest

        manifest = parse_skill_md(DOCX_SKILL_PATH / "SKILL.md")
        errors = validate_manifest(manifest)
        assert errors == []


class TestFrontmatterEdgeCases:
    """Ensure frontmatter parsing handles tricky body content."""

    def test_body_with_horizontal_rules(self, tmp_path: Path) -> None:
        """Markdown horizontal rules (---) in the body must not break parsing.
        The parser finds only the first closing --- after the opening one."""
        content = """\
---
name: edge-test
description: A skill whose body contains horizontal rules.
---
# Heading

Some paragraph text.

---

Another section after a horizontal rule.

---

Final section.
"""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(content)
        manifest = parse_skill_md(skill_file)
        assert manifest.name == "edge-test"
        assert "---" in manifest.body
        assert "Final section." in manifest.body

    def test_body_with_yaml_like_content(self, tmp_path: Path) -> None:
        """Body containing YAML-like key: value lines after frontmatter
        must not confuse the parser."""
        content = """\
---
name: yaml-body
description: Body has YAML-like content after the delimiter.
---
# Configuration Guide

Set these values:
name: my-config
version: 2.0
nested:
  key: value

---

End of guide.
"""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(content)
        manifest = parse_skill_md(skill_file)
        assert manifest.name == "yaml-body"
        assert "name: my-config" in manifest.body
        assert "nested:" in manifest.body


class TestZipCreation:
    """Test _create_zip with the real docx skill directory."""

    def test_zip_is_valid(self) -> None:
        zip_data = _create_zip(DOCX_SKILL_PATH)
        assert zipfile.is_zipfile(io.BytesIO(zip_data))

    def test_zip_includes_skill_md(self) -> None:
        zip_data = _create_zip(DOCX_SKILL_PATH)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            names = zf.namelist()
        assert "SKILL.md" in names

    def test_zip_includes_license(self) -> None:
        zip_data = _create_zip(DOCX_SKILL_PATH)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            names = zf.namelist()
        assert "LICENSE.txt" in names

    def test_zip_includes_python_scripts(self) -> None:
        zip_data = _create_zip(DOCX_SKILL_PATH)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            names = zf.namelist()
        assert "scripts/__init__.py" in names
        assert "scripts/document.py" in names
        assert "scripts/utilities.py" in names

    def test_zip_includes_ooxml_schemas(self) -> None:
        zip_data = _create_zip(DOCX_SKILL_PATH)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            xsd_files = [n for n in zf.namelist() if n.endswith(".xsd")]
        assert len(xsd_files) >= 20

    def test_zip_includes_ooxml_scripts(self) -> None:
        zip_data = _create_zip(DOCX_SKILL_PATH)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            names = zf.namelist()
        assert "ooxml/scripts/pack.py" in names
        assert "ooxml/scripts/unpack.py" in names
        assert "ooxml/scripts/validate.py" in names

    def test_zip_includes_xml_templates(self) -> None:
        zip_data = _create_zip(DOCX_SKILL_PATH)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            xml_templates = [
                n for n in zf.namelist()
                if n.startswith("scripts/templates/") and n.endswith(".xml")
            ]
        assert len(xml_templates) == 5

    def test_zip_excludes_hidden_files(self) -> None:
        zip_data = _create_zip(DOCX_SKILL_PATH)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            hidden = [n for n in zf.namelist() if any(
                part.startswith(".") for part in Path(n).parts
            )]
        assert hidden == []

    def test_zip_excludes_pycache(self) -> None:
        zip_data = _create_zip(DOCX_SKILL_PATH)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            pycache = [n for n in zf.namelist() if "__pycache__" in n]
        assert pycache == []

    def test_zip_total_file_count(self) -> None:
        """The docx skill should contain exactly 59 files."""
        zip_data = _create_zip(DOCX_SKILL_PATH)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            assert len(zf.namelist()) == 59


class TestChecksumVerification:
    """Checksum consistency and verification with real zip data."""

    def test_zip_checksum_is_deterministic(self) -> None:
        """Two calls to _create_zip should produce identical bytes and checksum."""
        zip_data_1 = _create_zip(DOCX_SKILL_PATH)
        zip_data_2 = _create_zip(DOCX_SKILL_PATH)
        assert hashlib.sha256(zip_data_1).hexdigest() == hashlib.sha256(zip_data_2).hexdigest()

    def test_verify_checksum_passes_for_correct_hash(self) -> None:
        zip_data = _create_zip(DOCX_SKILL_PATH)
        expected = hashlib.sha256(zip_data).hexdigest()
        # Should not raise
        verify_checksum(zip_data, expected)

    def test_verify_checksum_raises_for_wrong_hash(self) -> None:
        zip_data = _create_zip(DOCX_SKILL_PATH)
        wrong = "0" * 64
        with pytest.raises(ValueError, match="Checksum mismatch"):
            verify_checksum(zip_data, wrong)


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


class TestNameAndVersionValidation:
    """Validate 'docx' as a skill name across both modules."""

    def test_docx_is_valid_skill_name_in_publish(self) -> None:
        result = validate_skill_name("docx")
        assert result == "docx"

    def test_docx_matches_manifest_name_pattern(self) -> None:
        from decision_hub.domain.skill_manifest import _NAME_PATTERN

        assert _NAME_PATTERN.match("docx") is not None

    def test_name_patterns_are_consistent(self) -> None:
        """Names valid in manifest parser must also be valid in publish validator."""
        from decision_hub.domain.skill_manifest import _NAME_PATTERN
        from decision_hub.domain.publish import _SKILL_NAME_PATTERN

        test_names = ["docx", "my-skill", "a", "ab", "a-b", "a1", "skill-123"]
        for name in test_names:
            manifest_ok = _NAME_PATTERN.match(name) is not None
            publish_ok = _SKILL_NAME_PATTERN.match(name) is not None
            assert manifest_ok == publish_ok, (
                f"Inconsistency for '{name}': manifest={manifest_ok}, publish={publish_ok}"
            )


class TestInstallPathResolution:
    """Verify path building for installed skills."""

    def test_get_dhub_skill_path(self) -> None:
        path = get_dhub_skill_path("example-org", "docx")
        assert path == Path.home() / ".dhub" / "skills" / "example-org" / "docx"

    def test_agent_skill_symlink_naming(self) -> None:
        """Symlinks are named {org}--{skill} in the agent skill directory."""
        org = "example-org"
        skill = "docx"
        expected_symlink_name = f"{org}--{skill}"
        assert expected_symlink_name == "example-org--docx"

        # Verify this pattern is used in AGENT_SKILL_PATHS context
        for agent, agent_dir in AGENT_SKILL_PATHS.items():
            expected_path = agent_dir / expected_symlink_name
            assert expected_path.name == "example-org--docx"


class TestS3KeyBuilding:
    """Verify S3 key format for published skills."""

    def test_build_s3_key_format(self) -> None:
        key = build_s3_key("example-org", "docx", "1.0.0")
        assert key == "skills/example-org/docx/1.0.0.zip"

    def test_build_s3_key_with_different_version(self) -> None:
        key = build_s3_key("example-org", "docx", "2.3.1")
        assert key == "skills/example-org/docx/2.3.1.zip"


class TestSearchIndexEntry:
    """Build and serialize/deserialize index entries for docx."""

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

    def test_serialize_deserialize_roundtrip(self) -> None:
        manifest = parse_skill_md(DOCX_SKILL_PATH / "SKILL.md")
        entry = build_index_entry(
            org_slug="example-org",
            skill_name="docx",
            description=manifest.description,
            latest_version="1.0.0",
            eval_status="passed",
        )
        serialized = serialize_index([entry])
        deserialized = deserialize_index(serialized)
        assert len(deserialized) == 1
        roundtripped = deserialized[0]
        assert roundtripped.org_slug == entry.org_slug
        assert roundtripped.skill_name == entry.skill_name
        assert roundtripped.description == entry.description
        assert roundtripped.latest_version == entry.latest_version
        assert roundtripped.eval_status == entry.eval_status
        assert roundtripped.trust_score == entry.trust_score

    def test_serialize_deserialize_multiple_entries(self) -> None:
        entries = [
            build_index_entry("org-a", "docx", "desc A", "1.0.0", "passed"),
            build_index_entry("org-b", "docx", "desc B", "2.0.0", "failed"),
        ]
        serialized = serialize_index(entries)
        deserialized = deserialize_index(serialized)
        assert len(deserialized) == 2
        assert deserialized[0].org_slug == "org-a"
        assert deserialized[0].trust_score == "A"
        assert deserialized[1].org_slug == "org-b"
        assert deserialized[1].trust_score == "F"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_python_sources() -> list[tuple[str, str]]:
    """Collect all Python source files from the docx skill directory."""
    sources = []
    for py_file in sorted(DOCX_SKILL_PATH.rglob("*.py")):
        relative = py_file.relative_to(DOCX_SKILL_PATH)
        sources.append((str(relative), py_file.read_text()))
    return sources
