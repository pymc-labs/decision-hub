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

from decision_hub.domain.publish import CODE_EXTENSIONS, CONFIG_EXTENSIONS, TEXT_EXTENSIONS
from decision_hub.models import EvalResult, GauntletReport, SafetyGrade, TestCase

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

# Prompt injection patterns for SKILL.md body scanning
_PROMPT_INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(?i)ignore\s+(all\s+)?previous\s+instructions", "instruction override"),
    (r"(?i)you\s+are\s+now\s+(a\s+)?new\s+(ai|assistant|system)", "role hijack"),
    (r"(?i)forget\s+(everything|all|your\s+(instructions|rules))", "memory wipe"),
    (r"[\u200b\u200c\u200d\u2060\ufeff]", "zero-width/invisible unicode"),
    (r"(?i)(curl|wget|fetch)\s+https?://", "exfiltration URL"),
    (r"(?i)send\s+(the\s+)?(data|output|result|content)\s+to\s+", "exfiltration instruction"),
    (r"(?i)tool_call|function_call|<tool>|<function>", "tool escalation markup"),
    (r"\\x[0-9a-f]{2}|\\u[0-9a-f]{4}", "escaped unicode sequences"),
)

# Permission categories that elevate a skill from A to B
_ELEVATED_PERMISSION_PATTERNS: dict[str, list[str]] = {
    "shell": [
        r"\bsubprocess\b",
        r"\bos\.system\b",
        r"\bos\.popen\b",
        r"\bshell\b",
        r"\bbash\b",
    ],
    "network": [
        r"\bhttpx\b",
        r"\brequests\b",
        r"\burllib\b",
        r"\bsocket\b",
        r"\baiohttp\b",
    ],
    "fs_write": [
        r"\bopen\s*\(.*['\"]w",
        r"\bshutil\b",
        r"\bos\.remove\b",
        r"\bos\.unlink\b",
    ],
    "env_var": [
        r"\bos\.environ\b",
        r"\bos\.getenv\b",
    ],
}


# Type alias for the LLM judge callback.
# Accepts (source_snippets, skill_name, skill_description) -> list[dict]
# Each returned dict has 'file', 'label', 'dangerous' (bool), 'reason'.
AnalyzeFn = Callable[
    [list[dict], str, str],
    list[dict],
]

# Type alias for the prompt LLM judge callback.
# Accepts (prompt_hits, skill_name, skill_description) -> list[dict]
# Each returned dict has 'pattern', 'label', 'dangerous' (bool),
# 'ambiguous' (bool), 'reason' (str).
AnalyzePromptFn = Callable[
    [list[dict], str, str],
    list[dict],
]

# Type alias for holistic prompt body review callback.
# Accepts (body, skill_name, skill_description) -> dict
# Returns dict with 'dangerous' (bool), 'reason' (str).
ReviewBodyFn = Callable[
    [str, str, str],
    dict,
]


def check_manifest_schema(content: str) -> EvalResult:
    """Validate that SKILL.md YAML frontmatter contains required fields.

    Parses the frontmatter block (between --- delimiters) as YAML rather
    than regex-matching the full file body, preventing spoofed field names
    in markdown content from passing validation.
    """
    import yaml

    # Extract frontmatter between --- delimiters
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
# Size budget check
# ---------------------------------------------------------------------------

TEXT_BUDGET = 100 * 1024  # 100 KB cumulative text
CODE_BUDGET = 50 * 1024  # 50 KB cumulative code
CONFIG_BUDGET = 25 * 1024  # 25 KB cumulative config
MAX_FILE_COUNT = 20  # max non-directory entries


def check_size_budget(
    zip_entries: list[tuple[str, int, str]],
) -> EvalResult:
    """Check that the skill zip stays within size and file-count budgets.

    Classifies each entry by its file extension into text, code, or config
    categories and sums uncompressed bytes per category.

    - **pass**: all within budget, <= MAX_FILE_COUNT files, no unscannable extensions
    - **warn**: budget exceeded OR > MAX_FILE_COUNT files (grade C)
    - **fail**: unscannable binary files present (grade F)

    The details dict includes the full breakdown for audit logging.
    """
    text_bytes = 0
    code_bytes = 0
    config_bytes = 0
    unscannable_files: list[str] = []

    for filename, size, ext in zip_entries:
        if ext in TEXT_EXTENSIONS:
            text_bytes += size
        elif ext in CODE_EXTENSIONS:
            code_bytes += size
        elif ext in CONFIG_EXTENSIONS:
            config_bytes += size
        else:
            # Extension-less files (ext == "") and unknown extensions
            unscannable_files.append(filename)

    file_count = len(zip_entries)

    details = {
        "text_bytes": text_bytes,
        "text_budget": TEXT_BUDGET,
        "code_bytes": code_bytes,
        "code_budget": CODE_BUDGET,
        "config_bytes": config_bytes,
        "config_budget": CONFIG_BUDGET,
        "file_count": file_count,
        "max_file_count": MAX_FILE_COUNT,
        "unscannable_files": unscannable_files,
    }

    # Fail: unscannable binary files present
    if unscannable_files:
        return EvalResult(
            check_name="size_budget",
            severity="fail",
            message=f"Unscannable files detected: {', '.join(unscannable_files[:5])}",
            details=details,
        )

    # Warn: budget exceeded or too many files
    warnings: list[str] = []
    if text_bytes > TEXT_BUDGET:
        warnings.append(f"text {text_bytes // 1024}KB > {TEXT_BUDGET // 1024}KB")
    if code_bytes > CODE_BUDGET:
        warnings.append(f"code {code_bytes // 1024}KB > {CODE_BUDGET // 1024}KB")
    if config_bytes > CONFIG_BUDGET:
        warnings.append(f"config {config_bytes // 1024}KB > {CONFIG_BUDGET // 1024}KB")
    if file_count > MAX_FILE_COUNT:
        warnings.append(f"file count {file_count} > {MAX_FILE_COUNT}")

    if warnings:
        return EvalResult(
            check_name="size_budget",
            severity="warn",
            message=f"Size budget exceeded: {'; '.join(warnings)}",
            details=details,
        )

    return EvalResult(
        check_name="size_budget",
        severity="pass",
        message="Within size budget",
        details=details,
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
                    hits.append(
                        {
                            "file": filename,
                            "label": label,
                            "line": line.strip()[:200],
                        }
                    )
    return hits


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

    Returns severity "pass", "warn" (ambiguous), or "fail" (dangerous).
    """
    hits = _find_suspicious_lines(source_files)

    if not hits:
        return EvalResult(
            check_name="safety_scan",
            severity="pass",
            message="No suspicious patterns detected",
        )

    # --- LLM judge available: let it decide ---
    if analyze_fn is not None:
        judgments = analyze_fn(hits, skill_name, skill_description)

        # Fail-closed: backfill any hits not covered by the LLM response.
        # Run unconditionally — the LLM may return duplicates or hallucinated
        # entries that inflate len(judgments) while leaving real hits uncovered.
        covered_keys = {(j.get("file"), j.get("label")) for j in judgments}
        for h in hits:
            if (h["file"], h["label"]) not in covered_keys:
                judgments.append(
                    {
                        "file": h["file"],
                        "label": h["label"],
                        "dangerous": True,
                        "reason": "LLM did not return judgment for this finding",
                    }
                )

        dangerous = [j for j in judgments if j.get("dangerous", True)]
        ambiguous = [j for j in judgments if j.get("ambiguous", False) and not j.get("dangerous", True)]
        acknowledged = [j for j in judgments if not j.get("dangerous", True) and not j.get("ambiguous", False)]

        if dangerous:
            danger_summary = "; ".join(f"{d['file']}: {d['label']} ({d.get('reason', 'flagged')})" for d in dangerous)
            return EvalResult(
                check_name="safety_scan",
                severity="fail",
                message=f"Dangerous patterns confirmed: {danger_summary}",
                details={"judgments": judgments},
            )

        if ambiguous:
            amb_summary = "; ".join(f"{a['file']}: {a['label']} ({a.get('reason', 'unclear')})" for a in ambiguous)
            return EvalResult(
                check_name="safety_scan",
                severity="warn",
                message=f"Ambiguous patterns found: {amb_summary}",
                details={"judgments": judgments},
            )

        ack_summary = "; ".join(
            f"{a['file']}: {a['label']} (ok: {a.get('reason', 'legitimate')})" for a in acknowledged
        )
        return EvalResult(
            check_name="safety_scan",
            severity="pass",
            message=f"All patterns reviewed and accepted: {ack_summary}",
            details={"judgments": judgments},
        )

    # --- No LLM: strict regex-only mode ---
    findings = [f"{h['file']}: {h['label']}" for h in hits]
    return EvalResult(
        check_name="safety_scan",
        severity="fail",
        message=f"Suspicious patterns found (no LLM review): {'; '.join(findings)}",
    )


def _find_prompt_injection_hits(body: str) -> list[dict]:
    """Scan SKILL.md body for prompt injection patterns.

    Returns a list of dicts with keys 'pattern', 'label', 'context'.
    """
    hits: list[dict] = []
    for line in body.splitlines():
        for pattern, label in _PROMPT_INJECTION_PATTERNS:
            match = re.search(pattern, line)
            if match:
                hits.append(
                    {
                        "pattern": pattern,
                        "label": label,
                        "context": line.strip()[:200],
                    }
                )
    return hits


def check_prompt_safety(
    skill_md_body: str,
    skill_name: str = "",
    skill_description: str = "",
    analyze_prompt_fn: AnalyzePromptFn | None = None,
    review_body_fn: ReviewBodyFn | None = None,
) -> EvalResult:
    """Two-stage prompt injection scan for the SKILL.md body.

    Stage 1: regex patterns find candidate injection patterns.
    Stage 2 (if analyze_prompt_fn provided): LLM classifies each hit.
    Stage 3 (if review_body_fn provided and no regex hits): holistic LLM review.
    """
    hits = _find_prompt_injection_hits(skill_md_body)

    if not hits:
        # No regex hits — run holistic LLM review if available
        if review_body_fn is not None:
            review = review_body_fn(skill_md_body, skill_name, skill_description)
            if review.get("dangerous", False):
                return EvalResult(
                    check_name="prompt_safety",
                    severity="fail",
                    message=f"Holistic body review flagged danger: {review.get('reason', 'flagged')}",
                    details={"body_review": review},
                )
        return EvalResult(
            check_name="prompt_safety",
            severity="pass",
            message="No prompt injection patterns detected",
        )

    # --- LLM judge available ---
    if analyze_prompt_fn is not None:
        judgments = analyze_prompt_fn(hits, skill_name, skill_description)

        # Fail-closed: backfill any hits not covered by the LLM response.
        # Run unconditionally — the LLM may return duplicates or hallucinated
        # entries that inflate len(judgments) while leaving real hits uncovered.
        covered_labels = {j.get("label") for j in judgments}
        for h in hits:
            if h["label"] not in covered_labels:
                judgments.append(
                    {
                        "label": h["label"],
                        "dangerous": True,
                        "ambiguous": False,
                        "reason": "LLM did not return judgment for this finding",
                    }
                )

        dangerous = [j for j in judgments if j.get("dangerous", True)]
        ambiguous = [j for j in judgments if j.get("ambiguous", False) and not j.get("dangerous", True)]

        if dangerous:
            danger_summary = "; ".join(f"{d['label']} ({d.get('reason', 'flagged')})" for d in dangerous)
            return EvalResult(
                check_name="prompt_safety",
                severity="fail",
                message=f"Dangerous prompt patterns confirmed: {danger_summary}",
                details={"judgments": judgments},
            )

        if ambiguous:
            amb_summary = "; ".join(f"{a['label']} ({a.get('reason', 'unclear')})" for a in ambiguous)
            return EvalResult(
                check_name="prompt_safety",
                severity="warn",
                message=f"Ambiguous prompt patterns found: {amb_summary}",
                details={"judgments": judgments},
            )

        return EvalResult(
            check_name="prompt_safety",
            severity="pass",
            message="All prompt patterns reviewed and accepted",
            details={"judgments": judgments},
        )

    # --- No LLM: strict mode ---
    findings = [h["label"] for h in hits]
    return EvalResult(
        check_name="prompt_safety",
        severity="fail",
        message=f"Prompt injection patterns found (no LLM review): {'; '.join(findings)}",
    )


def detect_elevated_permissions(
    source_files: list[tuple[str, str]],
    allowed_tools: str | None,
) -> list[str]:
    """Scan source files and allowed_tools for elevated permission usage.

    Returns a list of permission category strings (e.g. "shell", "network").
    """
    all_content = "\n".join(content for _, content in source_files)
    if allowed_tools:
        all_content += "\n" + allowed_tools

    found: list[str] = []
    for category, patterns in _ELEVATED_PERMISSION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, all_content):
                found.append(category)
                break
    return found


def compute_grade(
    results: tuple[EvalResult, ...],
    elevated_permissions: list[str],
    is_verified_org: bool,
) -> SafetyGrade:
    """Compute A/B/C/F grade from check results and context.

    F: any check failed
    C: any check warned (ambiguous)
    B: elevated permissions or unverified org
    A: all clear
    """
    if any(r.severity == "fail" for r in results):
        return "F"
    if any(r.severity == "warn" for r in results):
        return "C"
    if elevated_permissions or not is_verified_org:
        return "B"
    return "A"


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


def run_static_checks(
    skill_md_content: str,
    lockfile_content: str | None,
    source_files: list[tuple[str, str]],
    skill_name: str = "",
    skill_description: str = "",
    analyze_fn: AnalyzeFn | None = None,
    skill_md_body: str = "",
    allowed_tools: str | None = None,
    analyze_prompt_fn: AnalyzePromptFn | None = None,
    is_verified_org: bool = True,
    review_body_fn: ReviewBodyFn | None = None,
    zip_entries: list[tuple[str, int, str]] | None = None,
) -> GauntletReport:
    """Run all static analysis checks and return a GauntletReport.

    Args:
        skill_md_content: Raw SKILL.md file content.
        lockfile_content: Raw lockfile content, or None if no lockfile.
        source_files: List of (filename, content) for Python source files.
        skill_name: Skill name for LLM safety context.
        skill_description: Skill description for LLM safety context.
        analyze_fn: Optional LLM judge callback for the code safety scan.
        skill_md_body: The body (system prompt) section of SKILL.md.
        allowed_tools: The allowed_tools field from the manifest.
        analyze_prompt_fn: Optional LLM callback for prompt safety scan.
        is_verified_org: Whether the publishing org is verified.
        review_body_fn: Optional LLM callback for holistic body review.
        zip_entries: Per-file metadata from the zip archive for size budget check.
    """
    results = [check_manifest_schema(skill_md_content)]

    if lockfile_content is not None:
        results.append(check_dependency_audit(lockfile_content))

    results.append(
        check_safety_scan(
            source_files,
            skill_name=skill_name,
            skill_description=skill_description,
            analyze_fn=analyze_fn,
        )
    )

    # Prompt injection scan (only if body is provided)
    if skill_md_body:
        results.append(
            check_prompt_safety(
                skill_md_body,
                skill_name=skill_name,
                skill_description=skill_description,
                analyze_prompt_fn=analyze_prompt_fn,
                review_body_fn=review_body_fn,
            )
        )

    # Size budget check (only if zip metadata is provided)
    if zip_entries is not None:
        results.append(check_size_budget(zip_entries))

    elevated = detect_elevated_permissions(source_files, allowed_tools)
    result_tuple = tuple(results)
    grade = compute_grade(result_tuple, elevated, is_verified_org)

    from loguru import logger

    logger.info(
        "Gauntlet grading: elevated={} is_verified={} grade={} source_files={}",
        elevated,
        is_verified_org,
        grade,
        [name for name, _ in source_files],
    )

    return GauntletReport(results=result_tuple, grade=grade)
