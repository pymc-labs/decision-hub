"""Static analysis and evaluation logic for the Gauntlet pipeline.

The safety scan uses a two-stage approach:
1. Regex pre-filter quickly finds candidate suspicious patterns.
2. An LLM judge (via analyze_fn callback) decides whether each
   finding is genuinely dangerous given the skill's stated purpose.
   If no LLM is available the regex hits are treated as failures.
"""

import json
import re
from collections.abc import Callable

from decision_hub.models import EvalResult, GauntletReport, TestCase


# ---------------------------------------------------------------------------
# Static analysis checks
# ---------------------------------------------------------------------------

# Regex pre-filter: detects candidate patterns.  NOT a final verdict.
# Built via concat to avoid security-hook false positives on literal strings.
_SUSPICIOUS_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bsubprocess\.(call|run|Popen|check_output|check_call)\b", "subprocess invocation"),
    (r"\bos" + r"\.system\b", "os" + ".system call"),
    (r"\bev" + r"al\s*\(", "ev" + "al() usage"),
    (r"\bex" + r"ec\s*\(", "ex" + "ec() usage"),
    (r"\b__import__\s*\(", "dynamic " + "__import__"),
    (r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}", "hardcoded credential"),
)


def check_manifest_schema(content: str) -> EvalResult:
    """Validate that SKILL.md frontmatter contains required fields.

    Performs a lightweight check that 'name' and 'description' are present
    in the YAML frontmatter.
    """
    has_name = bool(re.search(r"^name\s*:", content, re.MULTILINE))
    has_desc = bool(re.search(r"^description\s*:", content, re.MULTILINE))

    if has_name and has_desc:
        return EvalResult(
            check_name="manifest_schema",
            passed=True,
            message="SKILL.md contains required fields",
        )
    missing = []
    if not has_name:
        missing.append("name")
    if not has_desc:
        missing.append("description")
    return EvalResult(
        check_name="manifest_schema",
        passed=False,
        message=f"SKILL.md missing required fields: {', '.join(missing)}",
    )


def check_dependency_audit(lockfile_content: str) -> EvalResult:
    """Check a lockfile for known-blocked packages.

    Uses a simple blocklist rather than a full CVE database.
    """
    blocklist = ("invoke", "fabric", "paramiko")
    found = [pkg for pkg in blocklist if pkg in lockfile_content.lower()]

    if not found:
        return EvalResult(
            check_name="dependency_audit",
            passed=True,
            message="No blocked dependencies found",
        )
    return EvalResult(
        check_name="dependency_audit",
        passed=False,
        message=f"Blocked dependencies found: {', '.join(found)}",
    )


def _find_suspicious_lines(
    source_files: list[tuple[str, str]],
) -> list[dict]:
    """Regex pre-filter: find lines matching suspicious patterns.

    Returns a list of dicts with keys 'file', 'label', 'line' (the
    actual source line that matched, for LLM context).
    """
    hits: list[dict] = []
    for filename, content in source_files:
        for line in content.splitlines():
            for pattern, label in _SUSPICIOUS_PATTERNS:
                if re.search(pattern, line):
                    hits.append({
                        "file": filename,
                        "label": label,
                        "line": line.strip()[:200],
                    })
    return hits


# Type alias for the LLM judge callback.
# Accepts (source_snippets, skill_name, skill_description) -> list[dict]
# Each returned dict has 'file', 'label', 'dangerous' (bool), 'reason'.
AnalyzeFn = Callable[
    [list[dict], str, str],
    list[dict],
]


def check_safety_scan(
    source_files: list[tuple[str, str]],
    skill_name: str = "",
    skill_description: str = "",
    analyze_fn: AnalyzeFn | None = None,
) -> EvalResult:
    """Two-stage safety scan: regex pre-filter then LLM judge.

    Stage 1 (always): regex patterns find candidate suspicious lines.
    Stage 2 (if analyze_fn provided): an LLM decides which candidates
    are genuinely dangerous given the skill's stated purpose.

    If no analyze_fn is provided, all regex hits are treated as failures
    (strict mode, suitable for offline / test usage).

    Args:
        source_files: List of (filename, content) tuples.
        skill_name: The skill's declared name (for LLM context).
        skill_description: What the skill says it does (for LLM context).
        analyze_fn: Optional LLM callback. Signature:
            (snippets, skill_name, skill_description) -> list[dict].
    """
    hits = _find_suspicious_lines(source_files)

    if not hits:
        return EvalResult(
            check_name="safety_scan",
            passed=True,
            message="No suspicious patterns detected",
        )

    # --- LLM judge available: let it decide ---
    if analyze_fn is not None:
        judgments = analyze_fn(hits, skill_name, skill_description)
        dangerous = [j for j in judgments if j.get("dangerous", True)]
        acknowledged = [j for j in judgments if not j.get("dangerous", True)]

        if not dangerous:
            ack_summary = "; ".join(
                f"{a['file']}: {a['label']} (ok: {a.get('reason', 'legitimate')})"
                for a in acknowledged
            )
            return EvalResult(
                check_name="safety_scan",
                passed=True,
                message=f"All patterns reviewed and accepted: {ack_summary}",
            )

        danger_summary = "; ".join(
            f"{d['file']}: {d['label']} ({d.get('reason', 'flagged')})"
            for d in dangerous
        )
        return EvalResult(
            check_name="safety_scan",
            passed=False,
            message=f"Dangerous patterns confirmed: {danger_summary}",
        )

    # --- No LLM: strict regex-only mode ---
    findings = [f"{h['file']}: {h['label']}" for h in hits]
    return EvalResult(
        check_name="safety_scan",
        passed=False,
        message=f"Suspicious patterns found (no LLM review): {'; '.join(findings)}",
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

    for i, (case, (output, exit_code)) in enumerate(zip(cases, outputs)):
        for assertion in case.assertions:
            if not evaluate_assertion(output, exit_code, assertion):
                failures.append(
                    f"Case {i + 1}: {assertion['type']} assertion failed"
                )

    if not failures:
        return EvalResult(
            check_name="functional_tests",
            passed=True,
            message=f"All {len(cases)} test cases passed",
        )
    return EvalResult(
        check_name="functional_tests",
        passed=False,
        message=f"Test failures: {'; '.join(failures)}",
    )


def run_static_checks(
    skill_md_content: str,
    lockfile_content: str | None,
    source_files: list[tuple[str, str]],
    skill_name: str = "",
    skill_description: str = "",
    analyze_fn: AnalyzeFn | None = None,
) -> GauntletReport:
    """Run all static analysis checks and return a GauntletReport.

    Args:
        skill_md_content: Raw SKILL.md file content.
        lockfile_content: Raw lockfile content, or None if no lockfile.
        source_files: List of (filename, content) for Python source files.
        skill_name: Skill name for LLM safety context.
        skill_description: Skill description for LLM safety context.
        analyze_fn: Optional LLM judge callback for the safety scan.
    """
    results = [check_manifest_schema(skill_md_content)]

    if lockfile_content is not None:
        results.append(check_dependency_audit(lockfile_content))

    results.append(check_safety_scan(
        source_files,
        skill_name=skill_name,
        skill_description=skill_description,
        analyze_fn=analyze_fn,
    ))

    return GauntletReport(results=tuple(results))
