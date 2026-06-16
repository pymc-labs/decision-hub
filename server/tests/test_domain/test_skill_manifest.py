"""Tests for decision_hub.domain.skill_manifest -- extract_description."""

from decision_hub.domain.skill_manifest import extract_body, extract_description


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
        content = '---\nname: my-skill\ndescription: ""\n---\nBody\n'
        assert extract_description(content) == ""

    def test_handles_horizontal_rule_in_body(self) -> None:
        """The --- in the body should not break parsing."""
        content = "---\nname: my-skill\ndescription: Works well\n---\nBody\n\n---\n\nMore body\n"
        assert extract_description(content) == "Works well"

    def test_regex_fallback_when_yaml_parse_fails(self) -> None:
        """When YAML parsing chokes on the frontmatter (e.g. an unquoted
        colon in a tag-style value), extract_description must fall back
        to the regex path rather than silently returning an empty string."""
        # The `*notyaml` syntax is a YAML alias to a non-existent anchor,
        # which raises a ComposerError during safe_load and exercises the
        # regex fallback path while leaving a valid description line for
        # the regex to find.
        content = "---\nname: my-skill\ntag: *notyaml\ndescription: Picks the right side\n---\nBody\n"
        assert extract_description(content) == "Picks the right side"

    def test_regex_fallback_handles_unquoted_colon(self) -> None:
        """An unquoted colon in description is a common cause of YAML
        failure; the regex path must still return the value verbatim."""
        # `key: value: with colon` is a YAML mapping-merge error; the
        # regex captures everything after the first `description:`.
        content = "---\ndescription: tool: kubectl wrapper\n---\nBody\n"
        result = extract_description(content)
        assert result == "tool: kubectl wrapper"

    def test_regex_fallback_returns_empty_when_no_description(self) -> None:
        """If YAML fails AND no description line exists, return empty."""
        content = "---\nname: x\ntag: *broken\n---\nBody\n"
        assert extract_description(content) == ""


class TestExtractBody:
    """extract_body() returns the markdown body after the closing frontmatter."""

    def test_extracts_body(self) -> None:
        content = "---\nname: x\n---\nMy body text\nWith multiple lines\n"
        assert extract_body(content) == "My body text\nWith multiple lines"

    def test_empty_body_returns_empty_string(self) -> None:
        content = "---\nname: x\n---\n"
        assert extract_body(content) == ""

    def test_missing_frontmatter_returns_empty(self) -> None:
        """When the input has no frontmatter, return empty string instead
        of treating the whole document as the body."""
        assert extract_body("No frontmatter here\n") == ""

    def test_preserves_internal_horizontal_rule(self) -> None:
        """A `---` inside the body must not be misinterpreted as the
        frontmatter closer for a second frontmatter block."""
        content = "---\nname: x\n---\nFirst\n\n---\n\nSecond\n"
        assert extract_body(content) == "First\n\n---\n\nSecond"
