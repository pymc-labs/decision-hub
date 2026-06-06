"""Tests for decision_hub.domain.skill_manifest -- extract_description."""

import io
import zipfile

from decision_hub.domain.skill_manifest import extract_description, parse_eval_cases_from_zip


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


def _make_case_yaml(name: str) -> str:
    return f'name: {name}\ndescription: desc-{name}\nprompt: prompt-{name}\njudge_criteria: "PASS when it works"\n'


def _zip_with_entries(entries: list[tuple[str, str]]) -> bytes:
    """Build an in-memory zip where entries are written in the given order."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries:
            zf.writestr(name, content)
    return buf.getvalue()


class TestParseEvalCasesFromZip:
    """parse_eval_cases_from_zip walks evals/*.yaml in a deterministic order."""

    def test_returns_cases_sorted_by_filename(self) -> None:
        """Regardless of zip write order, cases come back sorted by entry name.

        The publish pipeline records eval cases in the order this function
        returns them; non-deterministic ordering meant the same skill content
        could produce different report orderings on different uploads. The
        fix sorts ``zf.namelist()`` before iteration.
        """
        # Intentionally write entries in reverse alphabetical order.
        zip_bytes = _zip_with_entries(
            [
                ("evals/z_case.yaml", _make_case_yaml("z")),
                ("evals/m_case.yaml", _make_case_yaml("m")),
                ("evals/a_case.yaml", _make_case_yaml("a")),
            ]
        )
        cases = parse_eval_cases_from_zip(zip_bytes)
        assert [c.name for c in cases] == ["a", "m", "z"]

    def test_ignores_non_yaml_entries(self) -> None:
        zip_bytes = _zip_with_entries(
            [
                ("evals/case.yaml", _make_case_yaml("only")),
                ("evals/README.md", "# not a case"),
                ("SKILL.md", "---\nname: x\n---\n"),
                ("other/file.yaml", _make_case_yaml("outside")),
            ]
        )
        cases = parse_eval_cases_from_zip(zip_bytes)
        assert [c.name for c in cases] == ["only"]
