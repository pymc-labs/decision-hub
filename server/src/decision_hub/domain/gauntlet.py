"""Static analysis and evaluation logic for the Gauntlet pipeline.

The safety scan uses a two-stage approach:
1. Regex pre-filter quickly finds candidate suspicious patterns.
2. An LLM judge (via analyze_fn callback) decides whether each
   finding is genuinely dangerous given the skill's stated purpose.
   If no LLM is available the regex hits are treated as failures.
"""

import json
import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from enum import Flag, auto

from decision_hub.infra.gemini import (
    LLM_BODY_REVIEW_CAP,
    LLM_HOLISTIC_TOTAL_CAP,
    LLM_PER_FILE_CAP,
)
from decision_hub.models import EvalResult, GauntletReport, SafetyGrade, TestCase

# ---------------------------------------------------------------------------
# Static analysis checks
# ---------------------------------------------------------------------------

# Regex pre-filter: detects candidate patterns.  NOT a final verdict.
# Built via concat to avoid security-hook false positives on literal strings.
_SUSPICIOUS_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bsubprocess\.(call|run|Popen|check_output|check_call)\b"), "subprocess invocation"),
    (re.compile(r"\bos" + r"\.system\b"), "os" + ".system call"),
    (re.compile(r"\bev" + r"al\s*\("), "ev" + "al() usage"),
    (re.compile(r"\bex" + r"ec\s*\("), "ex" + "ec() usage"),
    (re.compile(r"\b__import__\s*\("), "dynamic " + "__import__"),
    (re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][^'\"]{8,}"), "hardcoded credential"),
    (re.compile(r"\bfrom\s+subprocess\s+import\b"), "subprocess import"),
    (re.compile(r"\bfrom\s+os\s+import\s+.*\b" + "system" + r"\b"), "os" + ".system import"),
    (re.compile(r"\bfrom\s+os\s+import\s+.*\b" + "popen" + r"\b"), "os" + ".popen import"),
    (re.compile(r"\bimportlib\.import_module\s*\("), "dynamic importlib import"),
)

# ---------------------------------------------------------------------------
# Always-fail pattern combos — these co-occurring patterns are dangerous
# regardless of LLM judgment (same philosophy as Layer 1 credential patterns).
# ---------------------------------------------------------------------------
# Built via concat to avoid triggering security-hook false positives.
_ALWAYS_FAIL_COMBOS: tuple[tuple[tuple[re.Pattern, ...], str], ...] = (
    # exec/eval + network = data exfiltration via code execution
    (
        (re.compile(r"\bex" + r"ec\s*\("), re.compile(r"\b(requests|httpx|urllib)\.(post|put|get)\b")),
        "ex" + "ec() with network call in same file",
    ),
    (
        (re.compile(r"\bev" + r"al\s*\("), re.compile(r"\b(requests|httpx|urllib)\.(post|put|get)\b")),
        "ev" + "al() with network call in same file",
    ),
    # exec/eval + file read + network = read-exec-exfil chain
    (
        (re.compile(r"\bex" + r"ec\s*\("), re.compile(r"\bopen\s*\("), re.compile(r"\b(requests|httpx|urllib)\b")),
        "ex" + "ec() with file read and network in same file",
    ),
)


def _check_always_fail_combos(source_files: list[tuple[str, str]]) -> list[dict]:
    """Check for pattern combinations that are always dangerous."""
    findings: list[dict] = []
    for filename, content in source_files:
        for patterns, label in _ALWAYS_FAIL_COMBOS:
            if all(p.search(content) for p in patterns):
                findings.append({"file": filename, "label": label})
    return findings


# Prompt injection patterns for SKILL.md body scanning
_PROMPT_INJECTION_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"(?i)ignore\s+(all\s+)?previous\s+instructions"), "instruction override"),
    (re.compile(r"(?i)you\s+are\s+now\s+(a\s+)?new\s+(ai|assistant|system)"), "role hijack"),
    (re.compile(r"(?i)forget\s+(everything|all|your\s+(instructions|rules))"), "memory wipe"),
    (re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]"), "zero-width/invisible unicode"),
    (re.compile(r"(?i)(curl|wget|fetch)\s+https?://"), "exfiltration URL"),
    (re.compile(r"(?i)send\s+(the\s+)?(data|output|result|content)\s+to\s+"), "exfiltration instruction"),
    (re.compile(r"(?i)tool_call|function_call|<tool>|<function>"), "tool escalation markup"),
    (re.compile(r"\\x[0-9a-f]{2}|\\u[0-9a-f]{4}"), "escaped unicode sequences"),
)

# ---------------------------------------------------------------------------
# Embedded-credential detection (two layers)
# ---------------------------------------------------------------------------
#
# Layer 1 — Known-format patterns: high-confidence regexes for provider-
#   specific key prefixes.  Matches get a descriptive label ("AWS access
#   key") and always cause rejection.
# Layer 2 — Entropy scanner: extracts string literals and flags those whose
#   Shannon entropy exceeds a threshold.  Catches novel/unknown credential
#   formats automatically, since real secrets are far more random than
#   ordinary code strings.
#
# Both layers always reject (no LLM override) because embedded credentials
# are never legitimate in a published skill.
# Patterns built via concat to avoid triggering secret-scanning hooks.

_CREDENTIAL_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    # AWS access key IDs
    (re.compile("AKI" + r"A[0-9A-Z]{16}"), "AWS access key"),
    # GitHub tokens (classic & fine-grained)
    (re.compile("gh" + r"[ps]_[A-Za-z0-9_]{36,}"), "GitHub token"),
    (re.compile("github_pat" + r"_[A-Za-z0-9_]{22,}"), "GitHub personal access token"),
    # Slack tokens
    (re.compile("xox" + r"[bpras]-[A-Za-z0-9-]{10,}"), "Slack token"),
    # Stripe secret / restricted keys
    (re.compile("sk_live" + r"_[A-Za-z0-9]{24,}"), "Stripe secret key"),
    (re.compile("rk_live" + r"_[A-Za-z0-9]{24,}"), "Stripe restricted key"),
    # Google API keys
    (re.compile("AIza" + r"[0-9A-Za-z_-]{35}"), "Google API key"),
    # PEM private keys
    (re.compile(r"-----BEGIN[ A-Z]*PRIVATE KEY-----"), "private key"),
    # Anthropic API keys
    (re.compile("sk-ant" + r"-[A-Za-z0-9_-]{20,}"), "Anthropic API key"),
    # OpenAI API keys (48+ chars after prefix)
    (re.compile("sk-" + r"[A-Za-z0-9]{48,}"), "OpenAI API key"),
    # JWT tokens (header.payload.signature)
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "JWT token"),
)

# Entropy thresholds — charset-aware, following the trufflehog approach.
# Hex charset (0-9a-f) has a theoretical max of 4.0 bits, so a lower
# threshold is needed.  The full base64/printable charset can reach ~6 bits.
_ENTROPY_MIN_LENGTH = 20
_ENTROPY_THRESHOLD_HEX = 3.0
_ENTROPY_THRESHOLD_DEFAULT = 4.5
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")

# Regex to extract string literals (single or double quoted)
_STRING_LITERAL_RE = re.compile(r"""(['"])([^'"]{20,})\1""")

# False-positive allowlist: strings matching these patterns are not secrets
# even if high-entropy (UUIDs used as format examples, URL paths, etc.)
_ENTROPY_ALLOWLIST_RE = re.compile(
    r"^("
    r"https?://"  # URLs
    r"|/[a-z]"  # Unix paths
    r"|[a-z]+\.[a-z]"  # dotted module paths
    r"|(?-i:[A-Z_]{20,})$"  # ALL_CAPS constants / env var names (case-sensitive)
    r"|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"  # UUIDs
    r"|YOUR_|CHANGE_ME|REPLACE|PLACEHOLDER|TODO|FIXME|EXAMPLE|DUMMY|FAKE|TEST"
    r"|.*\{[a-zA-Z_]\w*\}"  # f-string/template interpolation ({var_name})
    r")",
    re.IGNORECASE,
)


# Type alias for the credential LLM judge callback.
# Accepts (hits, skill_name, skill_description) -> list[dict]
# Each returned dict has 'source', 'label', 'line', 'dangerous' (bool), 'reason'.
AnalyzeCredentialFn = Callable[
    [list[dict], str, str],
    list[dict],
]

# ---------------------------------------------------------------------------
# Shell pipeline taint tracking
# ---------------------------------------------------------------------------


class Taint(Flag):
    """Taint categories for tracking data flow through shell pipelines."""

    NONE = 0
    SENSITIVE_DATA = auto()  # reading secrets/credentials/keys
    USER_INPUT = auto()  # env vars, stdin, args
    OBFUSCATION = auto()  # encoding/encryption
    NETWORK_SEND = auto()  # exfiltration sink
    CODE_EXEC = auto()  # execution sink


@dataclass(frozen=True)
class TaintFinding:
    """A single taint-tracking finding from pipeline analysis."""

    source_cmd: str
    sink_cmd: str
    taint_flags: Taint
    severity: str  # "fail" or "warn"
    description: str


# Commands that produce sensitive data (taint sources)
_TAINT_SOURCE_PATTERNS: tuple[tuple[re.Pattern, Taint], ...] = (
    (re.compile(r"cat\s+(/etc/passwd|/etc/shadow)"), Taint.SENSITIVE_DATA),
    (re.compile(r"cat\s+~?/?\.(ssh|aws|gnupg|env)"), Taint.SENSITIVE_DATA),
    (re.compile(r"cat\s+.*\.(pem|key|crt|p12)"), Taint.SENSITIVE_DATA),
    (re.compile(r"\b(printenv|env)\b"), Taint.USER_INPUT),
    (re.compile(r"\$\{?\w*(KEY|TOKEN|SECRET|PASS)\w*\}?"), Taint.SENSITIVE_DATA),
)

# Commands that transform data (propagate taint, may add OBFUSCATION)
_TAINT_TRANSFORM_CMDS: dict[str, Taint] = {
    "base64": Taint.OBFUSCATION,
    "openssl": Taint.OBFUSCATION,
    "xxd": Taint.OBFUSCATION,
    "gzip": Taint.OBFUSCATION,
    "bzip2": Taint.OBFUSCATION,
    "xz": Taint.OBFUSCATION,
    "sed": Taint.NONE,
    "awk": Taint.NONE,
    "grep": Taint.NONE,
    "cut": Taint.NONE,
    "tr": Taint.NONE,
    "sort": Taint.NONE,
    "head": Taint.NONE,
    "tail": Taint.NONE,
}

# Commands that are sinks (consume tainted data)
_TAINT_SINK_CMDS: dict[str, Taint] = {
    "curl": Taint.NETWORK_SEND,
    "wget": Taint.NETWORK_SEND,
    "nc": Taint.NETWORK_SEND,
    "ncat": Taint.NETWORK_SEND,
    "bash": Taint.CODE_EXEC,
    "sh": Taint.CODE_EXEC,
    "python": Taint.CODE_EXEC,
    "python3": Taint.CODE_EXEC,
    "perl": Taint.CODE_EXEC,
    "ruby": Taint.CODE_EXEC,
}

# Regex to extract shell command strings from Python source
_SHELL_CMD_RE = re.compile(
    r"""(?:subprocess\.(?:run|call|Popen|check_output|check_call)\s*\(\s*"""
    r"""(?:f?(?:"([^"]*?)"|'([^']*?)'))|"""
    r"""os\.(?:system|popen)\s*\(\s*"""
    r"""(?:f?(?:"([^"]*?)"|'([^']*?)')))""",
    re.DOTALL,
)

# Regex to extract shell commands from list-form subprocess calls with
# shell interpreters: subprocess.run(["bash", "-c", "actual command"])
# Captures the command string (group 1) passed to the shell interpreter.
_SHELL_LIST_CMD_RE = re.compile(
    r"""subprocess\.(?:run|call|Popen|check_output|check_call)\s*\(\s*\["""
    r"""\s*(?:"|')(?:bash|sh|zsh)(?:"|')"""  # ["bash" or ["sh" or ["zsh"
    r"""\s*,\s*(?:"|')-\w*c(?:"|')"""  # , "-c" or "-lc" etc
    r"""\s*,\s*(?:"([^"]*?)"|'([^']*?)')"""  # , "actual command" (matched quotes)
    r"""\s*\]""",
    re.DOTALL,
)

# Regex to split shell commands on pipe, semicolon, or &&
_PIPE_SPLIT_RE = re.compile(r"\s*(?:\|{1,2}|;|&&)\s*")


def _classify_segment(segment: str) -> tuple[str, Taint | None]:
    """Classify a single pipeline segment as source, transform, or sink.

    Returns (role, taint) where role is 'source', 'transform', 'sink', or 'unknown'.
    """
    stripped = segment.strip()
    first_word = stripped.split()[0] if stripped.split() else ""

    # Check sinks first (curl, bash, etc.)
    if first_word in _TAINT_SINK_CMDS:
        return "sink", _TAINT_SINK_CMDS[first_word]

    # Check transforms
    if first_word in _TAINT_TRANSFORM_CMDS:
        return "transform", _TAINT_TRANSFORM_CMDS[first_word]

    # Check sources (pattern-based)
    for pattern, taint in _TAINT_SOURCE_PATTERNS:
        if pattern.search(stripped):
            return "source", taint

    return "unknown", Taint.NONE


def trace_pipeline_taint(command: str) -> list[TaintFinding]:
    """Split shell command on | ; && and track taint through the pipeline.

    Returns a list of TaintFinding for each case where tainted data reaches a sink.
    """
    segments = _PIPE_SPLIT_RE.split(command)
    if len(segments) < 2:
        return []

    findings: list[TaintFinding] = []
    accumulated_taint = Taint.NONE
    source_cmd = ""

    for segment in segments:
        role, taint = _classify_segment(segment)

        if role == "source" and taint is not None:
            accumulated_taint = accumulated_taint | taint
            source_cmd = segment.strip()
        elif role == "transform":
            if accumulated_taint != Taint.NONE and taint is not None:
                accumulated_taint = accumulated_taint | taint
        elif role == "sink" and accumulated_taint != Taint.NONE and taint is not None:
            combined = accumulated_taint | taint
            # Determine severity
            has_sensitive = bool(accumulated_taint & Taint.SENSITIVE_DATA)
            has_network = bool(taint & Taint.NETWORK_SEND)
            has_obfuscation = bool(accumulated_taint & Taint.OBFUSCATION)

            if has_sensitive and has_network and has_obfuscation:
                severity = "fail"
                desc = "Sensitive data obfuscated and sent to network"
            elif has_sensitive and has_network:
                severity = "fail"
                desc = "Sensitive data sent to network"
            elif has_sensitive and bool(taint & Taint.CODE_EXEC):
                severity = "warn"
                desc = "Sensitive data piped to code execution"
            else:
                severity = "warn"
                desc = "Tainted data reaches a sink"

            findings.append(
                TaintFinding(
                    source_cmd=source_cmd,
                    sink_cmd=segment.strip(),
                    taint_flags=combined,
                    severity=severity,
                    description=desc,
                )
            )

    return findings


def _extract_shell_commands(source_files: list[tuple[str, str]], skill_md_body: str) -> list[tuple[str, str]]:
    """Extract shell command strings from source files and SKILL.md body.

    Returns list of (source_label, command_string).
    """
    commands: list[tuple[str, str]] = []

    for filename, content in source_files:
        for match in _SHELL_CMD_RE.finditer(content):
            cmd = match.group(1) or match.group(2) or match.group(3) or match.group(4)
            if cmd:
                commands.append((filename, cmd))
        # List-form subprocess with shell interpreters: ["bash", "-c", "cmd"]
        for match in _SHELL_LIST_CMD_RE.finditer(content):
            cmd = match.group(1) or match.group(2)
            if cmd:
                commands.append((filename, cmd))

    # Also scan SKILL.md for bare shell commands in code blocks
    if skill_md_body:
        in_code_block = False
        for line in skill_md_body.splitlines():
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block and _PIPE_SPLIT_RE.search(stripped):
                commands.append(("SKILL.md", stripped))

    return commands


def check_pipeline_taint(
    source_files: list[tuple[str, str]],
    skill_md_body: str = "",
) -> EvalResult:
    """Scan source files and SKILL.md for shell pipeline taint chains.

    Extracts shell commands and traces taint through pipelines.
    """
    commands = _extract_shell_commands(source_files, skill_md_body)
    all_findings: list[dict] = []

    for source_label, cmd in commands:
        findings = trace_pipeline_taint(cmd)
        for f in findings:
            all_findings.append(
                {
                    "source": source_label,
                    "command": cmd[:200],
                    "source_cmd": f.source_cmd,
                    "sink_cmd": f.sink_cmd,
                    "severity": f.severity,
                    "description": f.description,
                }
            )

    if not all_findings:
        return EvalResult(
            check_name="pipeline_taint",
            severity="pass",
            message="No dangerous shell pipeline chains detected",
        )

    # Use the worst severity found
    has_fail = any(f["severity"] == "fail" for f in all_findings)
    summaries = [f"{f['source']}: {f['description']} ({f['source_cmd']} -> {f['sink_cmd']})" for f in all_findings]

    return EvalResult(
        check_name="pipeline_taint",
        severity="fail" if has_fail else "warn",
        message=f"Dangerous shell pipeline chains: {'; '.join(summaries)}",
        details={"findings": all_findings},
    )


# Permission categories that elevate a skill from A to B
_ELEVATED_PERMISSION_PATTERNS: dict[str, list[re.Pattern]] = {
    "shell": [
        re.compile(r"\bsubprocess\b"),
        re.compile(r"\bos\.system\b"),
        re.compile(r"\bos\.popen\b"),
        re.compile(r"\bshell\b"),
        re.compile(r"\bbash\b"),
    ],
    "network": [
        re.compile(r"\bhttpx\b"),
        re.compile(r"\brequests\b"),
        re.compile(r"\burllib\b"),
        re.compile(r"\bsocket\b"),
        re.compile(r"\baiohttp\b"),
    ],
    "fs_write": [
        re.compile(r"\bopen\s*\(.*['\"]w"),
        re.compile(r"\bshutil\b"),
        re.compile(r"\bos\.remove\b"),
        re.compile(r"\bos\.unlink\b"),
    ],
    "env_var": [
        re.compile(r"\bos\.environ\b"),
        re.compile(r"\bos\.getenv\b"),
    ],
}


# Type alias for the LLM judge callback.
# Accepts (source_snippets, source_files, skill_name, skill_description) -> list[dict]
# Each returned dict has 'file', 'label', 'dangerous' (bool), 'reason'.
AnalyzeFn = Callable[
    [list[dict], list[tuple[str, str]], str, str],
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

# Type alias for holistic code review callback.
# Accepts (source_files, skill_name, skill_description) -> dict
# Returns dict with 'dangerous' (bool), 'reason' (str).
ReviewCodeFn = Callable[
    [list[tuple[str, str]], str, str],
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


def _shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy (bits per character) of a string."""
    if not s:
        return 0.0
    length = len(s)
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    return -sum((c / length) * math.log2(c / length) for c in freq.values())


def _find_credential_hits(
    content: str,
    source_label: str,
) -> tuple[list[dict], list[dict]]:
    """Scan content for embedded credentials (known patterns + entropy).

    Returns (known_hits, entropy_hits). Each hit is a dict with keys
    'source', 'label', 'line'. Known-pattern hits always fail; entropy
    hits are candidates for LLM review.
    """
    known_hits: list[dict] = []
    entropy_hits: list[dict] = []
    seen_lines: set[int] = set()

    for lineno, line in enumerate(content.splitlines()):
        # Layer 1: known-format patterns (high confidence, specific label)
        for pattern, label in _CREDENTIAL_PATTERNS:
            if pattern.search(line):
                known_hits.append(
                    {
                        "source": source_label,
                        "label": label,
                        "line": line.strip()[:200],
                    }
                )
                seen_lines.add(lineno)

        # Layer 2: entropy scan on string literals (catches unknown formats)
        if lineno not in seen_lines:
            for match in _STRING_LITERAL_RE.finditer(line):
                value = match.group(2)
                if len(value) < _ENTROPY_MIN_LENGTH:
                    continue
                if _ENTROPY_ALLOWLIST_RE.search(value):
                    continue
                # Charset-aware threshold: hex has lower max entropy
                threshold = _ENTROPY_THRESHOLD_HEX if _HEX_RE.match(value) else _ENTROPY_THRESHOLD_DEFAULT
                if _shannon_entropy(value) >= threshold:
                    entropy_hits.append(
                        {
                            "source": source_label,
                            "label": "high-entropy secret",
                            "line": line.strip()[:200],
                        }
                    )
                    seen_lines.add(lineno)
                    break  # one hit per line is enough

    return known_hits, entropy_hits


def check_embedded_credentials(
    skill_md_content: str,
    source_files: list[tuple[str, str]],
    skill_name: str = "",
    skill_description: str = "",
    analyze_credential_fn: AnalyzeCredentialFn | None = None,
) -> EvalResult:
    """Scan all skill content for embedded credentials.

    Two detection layers:
    1. Known-format patterns (AWS keys, GitHub tokens, private keys, etc.)
       — always fail, no LLM override.
    2. Shannon entropy analysis on string literals (catches unknown formats)
       — if an LLM judge is available, entropy hits are sent for review.
         Without LLM, entropy hits fail automatically (strict mode).
    """
    all_known: list[dict] = []
    all_entropy: list[dict] = []

    known, entropy = _find_credential_hits(skill_md_content, "SKILL.md")
    all_known.extend(known)
    all_entropy.extend(entropy)

    for filename, content in source_files:
        known, entropy = _find_credential_hits(content, filename)
        all_known.extend(known)
        all_entropy.extend(entropy)

    # Known-pattern hits always fail — no LLM override
    if all_known:
        findings = [f"{h['source']}: {h['label']}" for h in all_known]
        return EvalResult(
            check_name="embedded_credentials",
            severity="fail",
            message=f"Embedded credentials detected: {'; '.join(findings)}",
            details={"hits": all_known},
        )

    if not all_entropy:
        return EvalResult(
            check_name="embedded_credentials",
            severity="pass",
            message="No embedded credentials detected",
        )

    # --- LLM judge available: let it review entropy hits ---
    if analyze_credential_fn is not None:
        judgments = analyze_credential_fn(all_entropy, skill_name, skill_description)

        # Fail-closed: require one judgment per entropy hit, not per unique source.
        # Without this, two high-entropy strings in the same file would be
        # covered by a single safe judgment — the second string goes unjudged.
        hit_source_counts: Counter[str] = Counter()
        for h in all_entropy:
            hit_source_counts[h["source"]] += 1

        judgment_source_counts: Counter[str] = Counter()
        for j in judgments:
            judgment_source_counts[j.get("source", "")] += 1

        for source, needed in hit_source_counts.items():
            shortfall = needed - judgment_source_counts.get(source, 0)
            for _ in range(shortfall):
                judgments.append(
                    {
                        "source": source,
                        "label": "high-entropy secret",
                        "line": "",
                        "dangerous": True,
                        "reason": "LLM did not return judgment for this finding",
                    }
                )

        dangerous = [j for j in judgments if j.get("dangerous", True)]
        cleared = [j for j in judgments if not j.get("dangerous", True)]

        if dangerous:
            findings = [
                f"{d.get('source', '?')}: {d.get('label', 'high-entropy secret')} ({d.get('reason', 'flagged')})"
                for d in dangerous
            ]
            return EvalResult(
                check_name="embedded_credentials",
                severity="fail",
                message=f"Embedded credentials confirmed: {'; '.join(findings)}",
                details={"judgments": judgments},
            )

        cleared_summary = "; ".join(
            f"{c.get('source', '?')}: {c.get('label', 'high-entropy secret')} (ok: {c.get('reason', 'not a secret')})"
            for c in cleared
        )
        return EvalResult(
            check_name="embedded_credentials",
            severity="pass",
            message=f"Entropy hits reviewed and cleared: {cleared_summary}",
            details={"judgments": judgments},
        )

    # --- No LLM: strict mode, entropy hits fail automatically ---
    findings = [f"{h['source']}: {h['label']}" for h in all_entropy]
    return EvalResult(
        check_name="embedded_credentials",
        severity="fail",
        message=f"Embedded credentials detected: {'; '.join(findings)}",
        details={"hits": all_entropy},
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
                if pattern.search(line):
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
    review_code_fn: ReviewCodeFn | None = None,
) -> EvalResult:
    """Multi-stage safety scan: always-fail combos, regex, LLM judge, holistic review.

    Stage 0 (always): always-fail pattern combos — immediate rejection.
    Stage 1 (always): regex patterns find candidate suspicious lines.
    Stage 2 (if analyze_fn provided): an LLM decides which candidates
    are genuinely dangerous given the skill's stated purpose.
    Stage 3 (if review_code_fn provided and no regex hits): holistic LLM
    code review for patterns that evade regex.

    Returns severity "pass", "warn" (ambiguous), or "fail" (dangerous).
    """
    # Stage 0: always-fail combos (no LLM override, same as Layer 1 credentials)
    combo_findings = _check_always_fail_combos(source_files)
    if combo_findings:
        findings_str = "; ".join(f"{f['file']}: {f['label']}" for f in combo_findings)
        return EvalResult(
            check_name="safety_scan",
            severity="fail",
            message=f"Dangerous pattern combinations detected: {findings_str}",
            details={"always_fail_combos": combo_findings},
        )

    hits = _find_suspicious_lines(source_files)

    if not hits:
        # Stage 3: holistic LLM code review (mirrors check_prompt_safety pattern)
        if review_code_fn is not None:
            review = review_code_fn(source_files, skill_name, skill_description)
            if review.get("dangerous", False):
                return EvalResult(
                    check_name="safety_scan",
                    severity="fail",
                    message=f"Holistic code review flagged danger: {review.get('reason', 'flagged')}",
                    details={"code_review": review},
                )
        return EvalResult(
            check_name="safety_scan",
            severity="pass",
            message="No suspicious patterns detected",
        )

    # --- LLM judge available: let it decide ---
    if analyze_fn is not None:
        hit_filenames = {h["file"] for h in hits}
        hit_files = [(f, c) for f, c in source_files if f in hit_filenames]
        judgments = analyze_fn(hits, hit_files, skill_name, skill_description)

        # Fail-closed: require one judgment per hit, not per unique (file, label).
        # Without this, two subprocess.run calls in the same file with the same
        # regex label would be "covered" by a single safe LLM judgment — even if
        # only the first call is benign and the second is dangerous.
        hit_counts: Counter[tuple[str, str]] = Counter()
        for h in hits:
            hit_counts[(h["file"], h["label"])] += 1

        judgment_counts: Counter[tuple[str, str]] = Counter()
        for j in judgments:
            judgment_counts[(j.get("file", ""), j.get("label", ""))] += 1

        for key, needed in hit_counts.items():
            shortfall = needed - judgment_counts.get(key, 0)
            for _ in range(shortfall):
                judgments.append(
                    {
                        "file": key[0],
                        "label": key[1],
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

        # Stage 2 didn't fail — run holistic review on files that had no
        # regex hits. This prevents the "decoy" bypass where an attacker
        # places a benign regex trigger in one file so that malicious code
        # in other files is never sent to the LLM for review.
        non_hit_files = [(f, c) for f, c in source_files if f not in hit_filenames]
        if non_hit_files and review_code_fn is not None:
            non_hit_review = review_code_fn(non_hit_files, skill_name, skill_description)
            if non_hit_review.get("dangerous", False):
                return EvalResult(
                    check_name="safety_scan",
                    severity="fail",
                    message=f"Holistic review of non-hit files flagged danger: {non_hit_review.get('reason', 'flagged')}",
                    details={"judgments": judgments, "non_hit_review": non_hit_review},
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
            match = pattern.search(line)
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

        # Fail-closed: require one judgment per hit, not per unique label.
        # Without this, two "ignore all instructions" lines would be covered
        # by a single safe judgment — the second line goes unjudged.
        hit_label_counts: Counter[str] = Counter()
        for h in hits:
            hit_label_counts[h["label"]] += 1

        judgment_label_counts: Counter[str] = Counter()
        for j in judgments:
            judgment_label_counts[j.get("label", "")] += 1

        for label, needed in hit_label_counts.items():
            shortfall = needed - judgment_label_counts.get(label, 0)
            for _ in range(shortfall):
                judgments.append(
                    {
                        "label": label,
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
            if pattern.search(all_content):
                found.append(category)
                break
    return found


# Mapping from elevated permission categories to expected tool declarations
_PERMISSION_TO_TOOL_KEYWORDS: dict[str, list[str]] = {
    "shell": ["bash", "shell", "run_shell", "execute", "terminal", "command"],
    "network": ["http", "fetch", "request", "network", "api", "web"],
    "fs_write": ["write", "edit", "file", "create_file", "save"],
    "env_var": ["env", "environment", "config"],
}


def check_tool_declaration_consistency(
    elevated_permissions: list[str],
    allowed_tools: str | None,
) -> EvalResult:
    """Flag when code uses capabilities not declared in allowed-tools."""
    if not allowed_tools or not elevated_permissions:
        return EvalResult(
            check_name="tool_consistency",
            severity="pass",
            message="No tool declaration inconsistencies",
        )

    tools_lower = allowed_tools.lower()
    inconsistencies: list[str] = []
    for perm in elevated_permissions:
        keywords = _PERMISSION_TO_TOOL_KEYWORDS.get(perm, [])
        if not any(kw in tools_lower for kw in keywords):
            inconsistencies.append(perm)

    if inconsistencies:
        return EvalResult(
            check_name="tool_consistency",
            severity="warn",
            message=f"Code uses {inconsistencies} but allowed-tools doesn't declare matching capabilities",
            details={"inconsistencies": inconsistencies},
        )
    return EvalResult(
        check_name="tool_consistency",
        severity="pass",
        message="Tool declarations are consistent with code capabilities",
    )


def check_unscanned_files(unscanned_files: list[str]) -> EvalResult:
    """Warn if the zip contains files that the gauntlet cannot inspect.

    Files with extensions outside the scannable set (.py, .sh, .json, etc.)
    are silently skipped during extraction. This check flags their presence
    so the skill gets at least grade C rather than a false-clean A.
    """
    if not unscanned_files:
        return EvalResult(
            check_name="unscanned_files",
            severity="pass",
            message="All files in the archive are scannable",
        )
    return EvalResult(
        check_name="unscanned_files",
        severity="warn",
        message=(
            f"Archive contains {len(unscanned_files)} file(s) that cannot be "
            f"security-scanned: {', '.join(unscanned_files[:10])}" + (" ..." if len(unscanned_files) > 10 else "")
        ),
        details={"unscanned_files": unscanned_files},
    )


# 1MB total source cap — skills exceeding this can't be meaningfully scanned
_MAX_SOURCE_TOTAL = 1_000_000


def check_source_size(source_files: list[tuple[str, str]]) -> EvalResult:
    """Warn if total source content exceeds the scannable limit.

    Skills with more source than the cap can't be fully scanned by the
    gauntlet pipeline. Returns warn (grade C) rather than fail so the
    skill still publishes but is flagged as risky.
    """
    total = sum(len(content) for _, content in source_files)
    if total > _MAX_SOURCE_TOTAL:
        return EvalResult(
            check_name="source_size",
            severity="warn",
            message=(
                f"Total source content ({total:,} bytes) exceeds scan limit "
                f"({_MAX_SOURCE_TOTAL:,} bytes) — not all files could be scanned"
            ),
        )
    return EvalResult(
        check_name="source_size",
        severity="pass",
        message=f"Total source content ({total:,} bytes) within scan limit",
    )


# LLM review caps — imported from gemini.py (single source of truth).
# If content exceeds these caps, the LLM review truncates or drops
# files, meaning the skill was not fully scanned.


def check_llm_scan_coverage(
    source_files: list[tuple[str, str]],
    skill_md_body: str = "",
) -> EvalResult:
    """Warn if source or body exceeds LLM review caps.

    The LLM safety review truncates individual files, drops files past a
    total cap, and truncates the SKILL.md body. When any of these caps
    are hit, the skill was not fully scanned and should get at least
    grade C.
    """
    issues: list[str] = []

    oversized = [f for f, c in source_files if len(c) > LLM_PER_FILE_CAP]
    if oversized:
        names = ", ".join(oversized[:5]) + (" ..." if len(oversized) > 5 else "")
        issues.append(f"{len(oversized)} file(s) exceed per-file LLM cap ({LLM_PER_FILE_CAP // 1000}KB): {names}")

    # Note: we skip checking LLM_STAGE2_TOTAL_CAP here because Stage 2 only
    # receives files with regex hits (not all source files). Checking total
    # source against the Stage 2 cap would produce spurious warnings for
    # skills whose hit files are small.
    total_source = sum(len(c) for _, c in source_files)
    if total_source > LLM_HOLISTIC_TOTAL_CAP:
        issues.append(
            f"total source ({total_source:,} bytes) exceeds holistic review cap ({LLM_HOLISTIC_TOTAL_CAP // 1000}KB)"
        )

    if skill_md_body and len(skill_md_body) > LLM_BODY_REVIEW_CAP:
        issues.append(
            f"SKILL.md body ({len(skill_md_body):,} bytes) exceeds prompt review cap ({LLM_BODY_REVIEW_CAP // 1000}KB)"
        )

    if not issues:
        return EvalResult(
            check_name="llm_coverage",
            severity="pass",
            message="All content within LLM review limits",
        )
    return EvalResult(
        check_name="llm_coverage",
        severity="warn",
        message=f"Content exceeds LLM review limits — partial scan only: {'; '.join(issues)}",
    )


def compute_grade(
    results: tuple[EvalResult, ...],
    elevated_permissions: list[str],
) -> SafetyGrade:
    """Compute A/B/C/F grade from check results and context.

    F: any check failed
    C: any check warned (ambiguous)
    B: elevated permissions
    A: all clear
    """
    if any(r.severity == "fail" for r in results):
        return "F"
    if any(r.severity == "warn" for r in results):
        return "C"
    if elevated_permissions:
        return "B"
    return "A"


def build_gauntlet_summary(
    results: tuple[EvalResult, ...],
    elevated_permissions: list[str],
) -> str | None:
    """Build a brief human-readable summary of gauntlet findings.

    Returns None when all checks passed and no elevated permissions
    were detected (grade A). For grade B+, returns a summary like:
      "Elevated permissions: shell, network"
    For grade C, includes the warning messages:
      "3 unscanned files; total source exceeds LLM review cap"
    """
    parts: list[str] = []

    for r in results:
        if r.severity == "fail":
            parts.append(f"[FAIL] {r.check_name}: {r.message}")
        elif r.severity == "warn":
            parts.append(r.message)

    if elevated_permissions:
        parts.append(f"Elevated permissions: {', '.join(elevated_permissions)}")

    return "; ".join(parts) if parts else None


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
    review_body_fn: ReviewBodyFn | None = None,
    analyze_credential_fn: AnalyzeCredentialFn | None = None,
    review_code_fn: ReviewCodeFn | None = None,
    unscanned_files: list[str] | None = None,
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
        analyze_credential_fn: Optional LLM callback for entropy credential review.
        unscanned_files: Filenames in the zip that could not be security-scanned.
    """
    # Normalize: non-string allowed_tools (e.g. from malformed manifests) → None
    if not isinstance(allowed_tools, str):
        allowed_tools = None

    results = [check_manifest_schema(skill_md_content)]

    # Unscanned files check — warn if zip contains non-scannable file types
    results.append(check_unscanned_files(unscanned_files or []))

    # Source size check — warn if total source exceeds scan limit
    results.append(check_source_size(source_files))

    # LLM coverage check — warn if content exceeds LLM review caps
    results.append(check_llm_scan_coverage(source_files, skill_md_body))

    if lockfile_content is not None:
        results.append(check_dependency_audit(lockfile_content))

    # Fail-fast: if already failed (manifest, dependency), skip expensive LLM
    # calls but still run regex-only checks for complete findings.
    # Gate is checked in two phases: before credential LLM, and again after
    # credential check so a credential failure also skips later LLM calls.
    already_failed = any(r.severity == "fail" for r in results)

    results.append(
        check_embedded_credentials(
            skill_md_content,
            source_files,
            skill_name=skill_name,
            skill_description=skill_description,
            analyze_credential_fn=None if already_failed else analyze_credential_fn,
        )
    )

    already_failed = any(r.severity == "fail" for r in results)
    effective_analyze_fn = None if already_failed else analyze_fn
    effective_review_code_fn = None if already_failed else review_code_fn
    effective_analyze_prompt_fn = None if already_failed else analyze_prompt_fn
    effective_review_body_fn = None if already_failed else review_body_fn

    results.append(
        check_safety_scan(
            source_files,
            skill_name=skill_name,
            skill_description=skill_description,
            analyze_fn=effective_analyze_fn,
            review_code_fn=effective_review_code_fn,
        )
    )

    # Prompt injection scan (only if body is provided)
    if skill_md_body:
        results.append(
            check_prompt_safety(
                skill_md_body,
                skill_name=skill_name,
                skill_description=skill_description,
                analyze_prompt_fn=effective_analyze_prompt_fn,
                review_body_fn=effective_review_body_fn,
            )
        )

    # Pipeline taint tracking
    results.append(check_pipeline_taint(source_files, skill_md_body))

    elevated = detect_elevated_permissions(source_files, allowed_tools)

    # Tool-use vs declaration consistency
    results.append(check_tool_declaration_consistency(elevated, allowed_tools))

    result_tuple = tuple(results)
    grade = compute_grade(result_tuple, elevated)
    summary = build_gauntlet_summary(result_tuple, elevated)

    from loguru import logger

    logger.info(
        "Gauntlet grading: elevated={} grade={} source_files={}",
        elevated,
        grade,
        [name for name, _ in source_files],
    )

    return GauntletReport(results=result_tuple, grade=grade, gauntlet_summary=summary)
