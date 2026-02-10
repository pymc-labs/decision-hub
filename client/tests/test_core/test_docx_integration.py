"""Client-side integration tests using the real docx skill at ~/.claude/skills/docx/.

These tests validate the client domain layer against a real-world
skill directory, ensuring that parsing, packaging, validation, and
install work correctly with production-like content.
"""

import hashlib
import io
import zipfile
from pathlib import Path

import pytest

from dhub.cli.registry import _create_zip
from dhub.core.install import (
    AGENT_SKILL_PATHS,
    get_dhub_skill_path,
    verify_checksum,
)
from dhub.core.manifest import _NAME_PATTERN, parse_skill_md, validate_manifest
from dhub.core.validation import _SKILL_NAME_PATTERN, validate_skill_name

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
            xml_templates = [n for n in zf.namelist() if n.startswith("scripts/templates/") and n.endswith(".xml")]
        assert len(xml_templates) == 5

    def test_zip_excludes_hidden_files(self) -> None:
        zip_data = _create_zip(DOCX_SKILL_PATH)
        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            hidden = [n for n in zf.namelist() if any(part.startswith(".") for part in Path(n).parts)]
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


class TestNameAndVersionValidation:
    """Validate 'docx' as a skill name across both modules."""

    def test_docx_is_valid_skill_name_in_validation(self) -> None:
        result = validate_skill_name("docx")
        assert result == "docx"

    def test_docx_matches_manifest_name_pattern(self) -> None:
        assert _NAME_PATTERN.match("docx") is not None

    def test_name_patterns_are_consistent(self) -> None:
        """Names valid in manifest parser must also be valid in validation module."""
        test_names = ["docx", "my-skill", "a", "ab", "a-b", "a1", "skill-123"]
        for name in test_names:
            manifest_ok = _NAME_PATTERN.match(name) is not None
            validation_ok = _SKILL_NAME_PATTERN.match(name) is not None
            assert (
                manifest_ok == validation_ok
            ), f"Inconsistency for '{name}': manifest={manifest_ok}, validation={validation_ok}"


class TestInstallPathResolution:
    """Verify path building for installed skills."""

    def test_get_dhub_skill_path(self) -> None:
        path = get_dhub_skill_path("example-org", "docx")
        assert path == Path.home() / ".dhub" / "skills" / "example-org" / "docx"

    def test_agent_skill_symlink_naming(self) -> None:
        """Symlinks are named {skill} in the agent skill directory."""
        skill = "docx"

        # Verify the symlink name is just the skill name
        for _agent, agent_dir in AGENT_SKILL_PATHS.items():
            expected_path = agent_dir / skill
            assert expected_path.name == "docx"
