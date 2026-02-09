"""Tests for decision_hub.domain.skill_manifest -- extract_description and version parsing."""

from pathlib import Path
from textwrap import dedent

import pytest

from decision_hub.domain.skill_manifest import extract_description
from dhub_core.manifest import parse_skill_md


class TestExtractDescription:
    """extract_description() pulls description from SKILL.md frontmatter."""

    def test_extracts_description(self) -> None:
        content = "---\nname: my-skill\ndescription: A helpful skill\n---\nBody text\n"
        assert extract_description(content) == "A helpful skill"

    def test_returns_empty_for_missing_description(self) -> None:
        content = "---\nname: my-skill\n---\nBody text\n"
        assert extract_description(content) == ""

    def test_returns_empty_for_invalid_frontmatter(self) -> None:
        content = "No frontmatter at all"
        assert extract_description(content) == ""

    def test_returns_empty_for_non_mapping_frontmatter(self) -> None:
        content = "---\n- list\n- items\n---\nBody\n"
        assert extract_description(content) == ""

    def test_handles_multiline_description(self) -> None:
        content = "---\nname: my-skill\ndescription: A skill that does many things\n---\nBody\n"
        assert extract_description(content) == "A skill that does many things"

    def test_handles_empty_description_value(self) -> None:
        content = "---\nname: my-skill\ndescription: \"\"\n---\nBody\n"
        assert extract_description(content) == ""

    def test_handles_horizontal_rule_in_body(self) -> None:
        """The --- in the body should not break parsing."""
        content = "---\nname: my-skill\ndescription: Works well\n---\nBody\n\n---\n\nMore body\n"
        assert extract_description(content) == "Works well"


class TestVersionParsing:
    """parse_skill_md extracts optional version from frontmatter."""

    def test_parses_version_from_frontmatter(self, tmp_path: Path) -> None:
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(dedent("""\
            ---
            name: my-skill
            description: A test skill
            version: 1.2.3
            ---
            Body text here
        """))
        manifest = parse_skill_md(skill_md)
        assert manifest.version == "1.2.3"

    def test_version_none_when_omitted(self, tmp_path: Path) -> None:
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(dedent("""\
            ---
            name: my-skill
            description: A test skill
            ---
            Body text here
        """))
        manifest = parse_skill_md(skill_md)
        assert manifest.version is None

    def test_invalid_version_raises(self, tmp_path: Path) -> None:
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(dedent("""\
            ---
            name: my-skill
            description: A test skill
            version: abc
            ---
            Body text here
        """))
        with pytest.raises(ValueError, match="Invalid version"):
            parse_skill_md(skill_md)
