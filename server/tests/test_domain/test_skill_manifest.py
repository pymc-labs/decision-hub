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


class TestParseEvalCasesFromZip:
    """parse_eval_cases_from_zip() accepts both .yaml and .yml extensions."""

    @staticmethod
    def _case_yaml(name: str) -> str:
        return f"name: {name}\ndescription: test\nprompt: do something\njudge_criteria: PASS if ok\n"

    @staticmethod
    def _zip(entries: dict[str, str]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, content in entries.items():
                zf.writestr(name, content)
        return buf.getvalue()

    def test_dot_yml_extension_is_accepted(self) -> None:
        cases = parse_eval_cases_from_zip(self._zip({"evals/first.yml": self._case_yaml("first")}))
        assert len(cases) == 1
        assert cases[0].name == "first"

    def test_mixed_yaml_and_yml_all_parsed(self) -> None:
        cases = parse_eval_cases_from_zip(
            self._zip(
                {
                    "evals/a.yaml": self._case_yaml("a"),
                    "evals/b.yml": self._case_yaml("b"),
                }
            )
        )
        assert {c.name for c in cases} == {"a", "b"}
