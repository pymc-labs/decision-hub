"""Tests for domain/evals.py -- static analysis and test result checking."""

import json

import pytest

from decision_hub.domain.evals import (
    check_dependency_audit,
    check_manifest_schema,
    check_safety_scan,
    evaluate_assertion,
    evaluate_test_results,
    parse_test_cases,
    run_static_checks,
)


class TestCheckManifestSchema:
    def test_valid_manifest(self):
        content = "name: my-skill\ndescription: A skill.\n"
        result = check_manifest_schema(content)
        assert result.passed is True

    def test_missing_name(self):
        content = "description: A skill.\n"
        result = check_manifest_schema(content)
        assert result.passed is False
        assert "name" in result.message

    def test_missing_description(self):
        content = "name: my-skill\n"
        result = check_manifest_schema(content)
        assert result.passed is False
        assert "description" in result.message

    def test_missing_both(self):
        content = "version: 1.0.0\n"
        result = check_manifest_schema(content)
        assert result.passed is False


class TestCheckDependencyAudit:
    def test_clean_lockfile(self):
        lockfile = "requests==2.31.0\nhttpx==0.27.0\n"
        result = check_dependency_audit(lockfile)
        assert result.passed is True

    def test_blocked_dependency(self):
        lockfile = "requests==2.31.0\nparamiko==3.0.0\n"
        result = check_dependency_audit(lockfile)
        assert result.passed is False
        assert "paramiko" in result.message


class TestCheckSafetyScan:
    def test_clean_source(self):
        files = [("main.py", "def hello():\n    return 'world'\n")]
        result = check_safety_scan(files)
        assert result.passed is True

    def test_detects_dynamic_code_execution(self):
        # Tests that the scanner catches patterns like dynamic code running
        code = "result = " + "ev" + "al(user_input)\n"
        files = [("main.py", code)]
        result = check_safety_scan(files)
        assert result.passed is False

    def test_detects_subprocess(self):
        files = [("main.py", "subprocess.run(['ls'])\n")]
        result = check_safety_scan(files)
        assert result.passed is False

    def test_detects_hardcoded_credential(self):
        files = [("config.py", 'api_key = "sk-abcdef123456789"\n')]
        result = check_safety_scan(files)
        assert result.passed is False


class TestParseTestCases:
    def test_parse_valid(self):
        cases_json = json.dumps([
            {
                "prompt": "Hello",
                "assertions": [
                    {"type": "contains", "value": "world"},
                    {"type": "exit_code", "value": 0},
                ],
            }
        ])
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
            "p-value is 0.03", 0,
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
        cases = parse_test_cases(json.dumps([
            {"prompt": "test", "assertions": [{"type": "exit_code", "value": 0}]},
        ]))
        result = evaluate_test_results(cases, [("output", 0)])
        assert result.passed is True

    def test_failure(self):
        cases = parse_test_cases(json.dumps([
            {"prompt": "test", "assertions": [{"type": "exit_code", "value": 0}]},
        ]))
        result = evaluate_test_results(cases, [("output", 1)])
        assert result.passed is False


class TestSafetyScanWithLlmJudge:
    """Tests for the two-stage safety scan: regex pre-filter + LLM judge."""

    def _make_analyze_fn(self, all_safe: bool):
        """Return a fake analyze_fn that marks everything as safe or dangerous."""
        def fake_analyze(snippets, name, desc):
            return [
                {"file": s["file"], "label": s["label"],
                 "dangerous": not all_safe,
                 "reason": "test reason"}
                for s in snippets
            ]
        return fake_analyze

    def test_llm_approves_legitimate_subprocess(self):
        """When the LLM says subprocess is fine, the scan passes."""
        files = [("pack.py", "subprocess.run(['zip', '-r', 'out.zip', 'dir'])\n")]
        result = check_safety_scan(
            files,
            skill_name="docx",
            skill_description="Document creation and editing",
            analyze_fn=self._make_analyze_fn(all_safe=True),
        )
        assert result.passed is True
        assert "accepted" in result.message

    def test_llm_flags_dangerous_pattern(self):
        """When the LLM confirms danger, the scan fails."""
        files = [("main.py", "subprocess.run(user_input)\n")]
        result = check_safety_scan(
            files,
            skill_name="hello",
            skill_description="Says hello",
            analyze_fn=self._make_analyze_fn(all_safe=False),
        )
        assert result.passed is False
        assert "confirmed" in result.message

    def test_llm_mixed_findings(self):
        """LLM approves some findings and rejects others."""
        files = [
            ("pack.py", "subprocess.run(['zip'])\n"),
            ("main.py", 'api_key = "sk-1234567890abcdef"\n'),
        ]
        def mixed_analyze(snippets, name, desc):
            results = []
            for s in snippets:
                if "subprocess" in s["label"]:
                    results.append({**s, "dangerous": False, "reason": "packing tool"})
                else:
                    results.append({**s, "dangerous": True, "reason": "leaked credential"})
            return results

        result = check_safety_scan(
            files,
            skill_name="docx",
            skill_description="Document editing",
            analyze_fn=mixed_analyze,
        )
        assert result.passed is False
        assert "credential" in result.message

    def test_no_hits_skips_llm(self):
        """When regex finds nothing, the LLM is never called."""
        called = []
        def should_not_be_called(snippets, name, desc):
            called.append(True)
            return []

        files = [("main.py", "def hello(): pass\n")]
        result = check_safety_scan(
            files,
            skill_name="test",
            skill_description="test",
            analyze_fn=should_not_be_called,
        )
        assert result.passed is True
        assert len(called) == 0

    def test_no_analyze_fn_strict_mode(self):
        """Without an LLM, regex hits are treated as failures."""
        files = [("main.py", "subprocess.run(['ls'])\n")]
        result = check_safety_scan(files)
        assert result.passed is False
        assert "no LLM review" in result.message


class TestRunStaticChecks:
    def test_all_pass(self):
        report = run_static_checks(
            skill_md_content="name: foo\ndescription: bar\n",
            lockfile_content="requests==2.31.0\n",
            source_files=[("main.py", "def hello(): pass\n")],
        )
        assert report.passed is True

    def test_no_lockfile(self):
        report = run_static_checks(
            skill_md_content="name: foo\ndescription: bar\n",
            lockfile_content=None,
            source_files=[("main.py", "def hello(): pass\n")],
        )
        assert report.passed is True
        # manifest + safety, no dep audit
        assert len(report.results) == 2

    def test_with_analyze_fn_passes_through(self):
        """run_static_checks forwards analyze_fn to check_safety_scan."""
        def approve_all(snippets, name, desc):
            return [
                {**s, "dangerous": False, "reason": "approved"}
                for s in snippets
            ]

        report = run_static_checks(
            skill_md_content="name: foo\ndescription: bar\n",
            lockfile_content=None,
            source_files=[("main.py", "subprocess.run(['ls'])\n")],
            skill_name="foo",
            skill_description="bar",
            analyze_fn=approve_all,
        )
        assert report.passed is True
