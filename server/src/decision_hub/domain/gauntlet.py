"""Manifest validation, dependency audit, and test case evaluation.

The safety scanning functions that used to live here (regex patterns,
LLM judge callbacks, credential entropy detection, prompt injection
scanning) have been replaced by the cisco-ai-skill-scanner integration
in skill_scanner_bridge.py. This module retains only the dhub-specific
checks that skill-scanner doesn't cover.
"""

import json

import yaml

from decision_hub.models import EvalResult, TestCase

# ---------------------------------------------------------------------------
# Manifest schema validation (dhub-specific)
# ---------------------------------------------------------------------------


def check_manifest_schema(content: str) -> EvalResult:
    """Validate that SKILL.md YAML frontmatter contains required fields.

    Parses the frontmatter block (between --- delimiters) as YAML rather
    than regex-matching the full file body, preventing spoofed field names
    in markdown content from passing validation.
    """
    lines = content.split("\n")
    start = 0
    while start < len(lines) and lines[start].strip() == "":
        start += 1

    if start >= len(lines) or lines[start].strip() != "---":
        return EvalResult(
            check_name="manifest_schema",
            severity="fail",
            message="SKILL.md missing YAML frontmatter (no opening ---)",
        )

    end = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break

    if end is None:
        return EvalResult(
            check_name="manifest_schema",
            severity="fail",
            message="SKILL.md missing YAML frontmatter (no closing ---)",
        )

    frontmatter_str = "\n".join(lines[start + 1 : end])
    try:
        data = yaml.safe_load(frontmatter_str)
    except yaml.YAMLError as exc:
        return EvalResult(
            check_name="manifest_schema",
            severity="fail",
            message=f"SKILL.md frontmatter is not valid YAML: {exc}",
        )

    if not isinstance(data, dict):
        return EvalResult(
            check_name="manifest_schema",
            severity="fail",
            message="SKILL.md frontmatter must be a YAML mapping",
        )

    missing = []
    if not data.get("name"):
        missing.append("name")
    if not data.get("description"):
        missing.append("description")

    if missing:
        return EvalResult(
            check_name="manifest_schema",
            severity="fail",
            message=f"SKILL.md missing required fields: {', '.join(missing)}",
        )

    return EvalResult(
        check_name="manifest_schema",
        severity="pass",
        message="SKILL.md contains required fields",
    )


# ---------------------------------------------------------------------------
# Dependency audit (dhub-specific blocklist)
# ---------------------------------------------------------------------------


def check_dependency_audit(lockfile_content: str) -> EvalResult:
    """Check a lockfile for known-blocked packages.

    Uses a simple blocklist rather than a full CVE database.
    """
    blocklist = ("invoke", "fabric", "paramiko")
    found = [pkg for pkg in blocklist if pkg in lockfile_content.lower()]

    if not found:
        return EvalResult(
            check_name="dependency_audit",
            severity="pass",
            message="No blocked dependencies found",
        )
    return EvalResult(
        check_name="dependency_audit",
        severity="fail",
        message=f"Blocked dependencies found: {', '.join(found)}",
    )


# ---------------------------------------------------------------------------
# Test case parsing and evaluation
# ---------------------------------------------------------------------------


def parse_test_cases(cases_json: str) -> tuple[TestCase, ...]:
    """Parse a tests/cases.json string into TestCase objects.

    Args:
        cases_json: JSON string containing a list of test case objects.

    Returns:
        Tuple of TestCase instances.

    Raises:
        json.JSONDecodeError: If the input is not valid JSON.
        KeyError: If required fields are missing from a test case.
    """
    raw = json.loads(cases_json)
    return tuple(
        TestCase(
            prompt=case["prompt"],
            assertions=tuple(case["assertions"]),
        )
        for case in raw
    )


def evaluate_assertion(output: str, exit_code: int, assertion: dict) -> bool:
    """Evaluate a single assertion against command output.

    Assertion types:
    - contains: stdout must contain substring (case-insensitive)
    - contains_any: stdout must contain at least one substring
    - not_contains: stdout must NOT contain substring
    - exit_code: process must exit with this code
    - json_schema: stdout must be valid JSON (basic check)
    """
    atype = assertion["type"]

    if atype == "contains":
        return assertion["value"].lower() in output.lower()
    if atype == "contains_any":
        return any(v.lower() in output.lower() for v in assertion["values"])
    if atype == "not_contains":
        return assertion["value"].lower() not in output.lower()
    if atype == "exit_code":
        return exit_code == assertion["value"]
    if atype == "json_schema":
        try:
            json.loads(output)
            return True
        except json.JSONDecodeError:
            return False

    return False


def evaluate_test_results(
    cases: tuple[TestCase, ...],
    outputs: list[tuple[str, int]],
) -> EvalResult:
    """Evaluate test results against expected assertions.

    Args:
        cases: Parsed test cases with assertions.
        outputs: List of (stdout, exit_code) tuples from running each case.

    Returns:
        Aggregated EvalResult for all test cases.
    """
    failures: list[str] = []

    for i, (case, (output, exit_code)) in enumerate(zip(cases, outputs, strict=True)):
        for assertion in case.assertions:
            if not evaluate_assertion(output, exit_code, assertion):
                failures.append(f"Case {i + 1}: {assertion['type']} assertion failed")

    if not failures:
        return EvalResult(
            check_name="functional_tests",
            severity="pass",
            message=f"All {len(cases)} test cases passed",
        )
    return EvalResult(
        check_name="functional_tests",
        severity="fail",
        message=f"Test failures: {'; '.join(failures)}",
    )
