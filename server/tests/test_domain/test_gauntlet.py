"""Tests for domain/gauntlet.py -- manifest validation, dependency audit, and test cases."""

import json

import pytest

from decision_hub.domain.gauntlet import (
    check_dependency_audit,
    check_manifest_schema,
    evaluate_assertion,
    evaluate_test_results,
    parse_test_cases,
)


class TestCheckManifestSchema:
    def test_valid_manifest(self):
        content = "---\nname: my-skill\ndescription: A skill.\n---\nBody text\n"
        result = check_manifest_schema(content)
        assert result.passed is True
        assert result.severity == "pass"

    def test_missing_name(self):
        content = "---\ndescription: A skill.\n---\n"
        result = check_manifest_schema(content)
        assert result.passed is False
        assert result.severity == "fail"
        assert "name" in result.message

    def test_missing_description(self):
        content = "---\nname: my-skill\n---\n"
        result = check_manifest_schema(content)
        assert result.passed is False
        assert "description" in result.message

    def test_missing_both(self):
        content = "---\nversion: 1.0.0\n---\n"
        result = check_manifest_schema(content)
        assert result.passed is False

    def test_no_frontmatter_delimiters(self):
        content = "name: my-skill\ndescription: A skill.\n"
        result = check_manifest_schema(content)
        assert result.passed is False
        assert "frontmatter" in result.message.lower()

    def test_invalid_yaml(self):
        content = "---\n: : : invalid\n---\n"
        result = check_manifest_schema(content)
        assert result.passed is False

    def test_name_in_body_not_in_frontmatter(self):
        """Field names in body text should not pass validation."""
        content = "---\ndescription: A skill.\n---\nname: spoofed-in-body\n"
        result = check_manifest_schema(content)
        assert result.passed is False
        assert "name" in result.message


class TestCheckDependencyAudit:
    def test_clean_lockfile(self):
        lockfile = "requests==2.31.0\nhttpx==0.27.0\n"
        result = check_dependency_audit(lockfile)
        assert result.passed is True
        assert result.severity == "pass"

    def test_blocked_dependency(self):
        lockfile = "requests==2.31.0\nparamiko==3.0.0\n"
        result = check_dependency_audit(lockfile)
        assert result.passed is False
        assert result.severity == "fail"
        assert "paramiko" in result.message


class TestParseTestCases:
    def test_parse_valid(self):
        cases_json = json.dumps(
            [
                {
                    "prompt": "Hello",
                    "assertions": [
                        {"type": "contains", "value": "world"},
                        {"type": "exit_code", "value": 0},
                    ],
                }
            ]
        )
        cases = parse_test_cases(cases_json)
        assert len(cases) == 1
        assert cases[0].prompt == "Hello"
        assert len(cases[0].assertions) == 2

    def test_parse_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            parse_test_cases("not json")


class TestAssertionChecks:
    def test_contains_pass(self):
        assert evaluate_assertion("Hello World", 0, {"type": "contains", "value": "hello"})

    def test_contains_fail(self):
        assert not evaluate_assertion("Goodbye", 0, {"type": "contains", "value": "hello"})

    def test_contains_any_pass(self):
        assert evaluate_assertion(
            "p-value is 0.03",
            0,
            {"type": "contains_any", "values": ["p-value", "confidence"]},
        )

    def test_not_contains_pass(self):
        assert evaluate_assertion("Success", 0, {"type": "not_contains", "value": "error"})

    def test_not_contains_fail(self):
        assert not evaluate_assertion("Error occurred", 0, {"type": "not_contains", "value": "error"})

    def test_exit_code_pass(self):
        assert evaluate_assertion("", 0, {"type": "exit_code", "value": 0})

    def test_exit_code_fail(self):
        assert not evaluate_assertion("", 1, {"type": "exit_code", "value": 0})

    def test_json_schema_pass(self):
        assert evaluate_assertion('{"key": "value"}', 0, {"type": "json_schema"})

    def test_json_schema_fail(self):
        assert not evaluate_assertion("not json", 0, {"type": "json_schema"})


class TestResultsAggregation:
    def test_all_pass(self):
        cases = parse_test_cases(
            json.dumps(
                [
                    {"prompt": "test", "assertions": [{"type": "exit_code", "value": 0}]},
                ]
            )
        )
        result = evaluate_test_results(cases, [("output", 0)])
        assert result.passed is True

    def test_failure(self):
        cases = parse_test_cases(
            json.dumps(
                [
                    {"prompt": "test", "assertions": [{"type": "exit_code", "value": 0}]},
                ]
            )
        )
        result = evaluate_test_results(cases, [("output", 1)])
        assert result.passed is False
