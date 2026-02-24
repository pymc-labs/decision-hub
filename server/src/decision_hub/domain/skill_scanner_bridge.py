"""Adapter between cisco-ai-skill-scanner and dhub's publish pipeline.

Handles zip extraction, scanner configuration, result mapping, and
grade computation. All three code paths (publish endpoint, crawler,
tracker) call through this module instead of the old gauntlet.

Includes a monkey-patch for the Cisco scanner's Google GenAI SDK
schema sanitizer to work around upstream incompatibility with Gemini
structured output (union types like ``["string", "null"]`` are not
accepted by the SDK — see github.com/pymc-labs/decision-hub/issues/187).
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from decision_hub.models import SafetyGrade


def _fix_gemini_union_types(schema: Any) -> Any:
    """Recursively convert JSON Schema union types to Gemini-compatible form.

    The Cisco scanner's ``llm_response_schema.json`` uses
    ``{"type": ["string", "null"]}`` for nullable fields.  Google's GenAI
    SDK rejects arrays in the ``type`` field — it expects a single enum
    value plus ``nullable: true``.

    Transforms applied:
    * ``{"type": ["X", "null"]}`` → ``{"type": "X_UPPER", "nullable": true}``
    * ``{"type": "x"}`` → ``{"type": "X_UPPER"}``  (case normalisation)
    * Recurses into ``properties``, ``items``, and list values.
    """
    if isinstance(schema, list):
        return [_fix_gemini_union_types(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, list):
            types = list(value)
            has_null = "null" in types
            if has_null:
                types.remove("null")
            if len(types) == 0:
                raise NotImplementedError(f"Google GenAI SDK does not support null-only types: {value!r}")
            if len(types) > 1:
                raise NotImplementedError(f"Google GenAI SDK does not support multi-type unions: {value!r}")
            out["type"] = types[0].upper()
            if has_null:
                out["nullable"] = True
        elif key == "type" and isinstance(value, str):
            if value == "null":
                raise NotImplementedError("Google GenAI SDK does not support null-only types")
            out["type"] = value.upper()
        elif key == "additionalProperties":
            continue
        elif isinstance(value, dict):
            out[key] = _fix_gemini_union_types(value)
        elif isinstance(value, list):
            out[key] = [_fix_gemini_union_types(v) if isinstance(v, dict) else v for v in value]
        else:
            out[key] = value

    return out


_PATCHED = False


def _patch_gemini_schema_sanitizer() -> None:
    """Monkey-patch the Cisco scanner's schema sanitizer for Gemini compat.

    Replaces ``LLMRequestHandler._sanitize_schema_for_google`` with a
    version that handles union types.  Safe to call multiple times —
    only patches once.
    """
    global _PATCHED
    if _PATCHED:
        return

    try:
        from skill_scanner.core.analyzers.llm_request_handler import (
            LLMRequestHandler,
        )
    except ImportError:
        logger.warning("skill_scanner not installed — skipping Gemini schema patch")
        return

    def _patched_sanitize(self: Any, schema: dict[str, Any]) -> dict[str, Any]:
        return _fix_gemini_union_types(schema)

    LLMRequestHandler._sanitize_schema_for_google = _patched_sanitize  # type: ignore[assignment]
    _PATCHED = True
    logger.debug("Patched LLMRequestHandler._sanitize_schema_for_google for Gemini union-type compat")


# ---------------------------------------------------------------------------
# Scanner result dataclass (decoupled from skill-scanner types)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BridgeScanResult:
    """Normalized scan result returned by the bridge to callers."""

    is_safe: bool
    max_severity: str
    grade: SafetyGrade
    findings_count: int
    findings: list[dict]
    analyzers_used: list[str]
    analyzability_score: float | None
    scan_duration_ms: int
    policy_name: str | None
    policy_fingerprint: str | None
    full_report: dict
    meta_analysis: dict | None


# ---------------------------------------------------------------------------
# Grade mapping
# ---------------------------------------------------------------------------

_SEVERITY_TO_GRADE: dict[str, SafetyGrade] = {
    "CRITICAL": "F",
    "HIGH": "F",
    "MEDIUM": "C",
    "LOW": "A",
    "INFO": "A",
    "SAFE": "A",
}


def severity_to_grade(max_severity: str) -> SafetyGrade:
    """Map a skill-scanner severity string to a dhub safety grade."""
    return _SEVERITY_TO_GRADE.get(max_severity, "A")


# ---------------------------------------------------------------------------
# Scanner construction
# ---------------------------------------------------------------------------


def _build_analyzers(settings: Any) -> list[Any]:
    """Build the list of scan-phase analyzers (everything except MetaAnalyzer).

    MetaAnalyzer is a post-processing step called separately after the scan
    via :func:`_run_meta_analysis` — see cisco-ai-defense/skill-scanner#41.
    """
    from skill_scanner.core.analyzers import (
        BehavioralAnalyzer,
        LLMAnalyzer,
        StaticAnalyzer,
        TriggerAnalyzer,
    )

    api_key = getattr(settings, "google_api_key", None)
    model = getattr(settings, "gemini_model", "gemini-2.0-flash")

    analyzers: list[Any] = [
        StaticAnalyzer(),
        BehavioralAnalyzer(),
        TriggerAnalyzer(),
    ]

    if api_key:
        analyzers.append(LLMAnalyzer(model=model, api_key=api_key))

    return analyzers


def _build_scanner(settings: Any) -> Any:
    """Build a SkillScanner configured for Scenario C (full pipeline)."""
    from skill_scanner import SkillScanner

    _patch_gemini_schema_sanitizer()
    analyzers = _build_analyzers(settings)
    return SkillScanner(analyzers=analyzers)


def _run_meta_analysis(
    result: Any, skill_dir: Path, settings: Any
) -> tuple[dict | None, list[Any]]:
    """Run MetaAnalyzer as a post-processing step on scan findings.

    Follows the same pattern as the scanner's CLI (``--enable-meta``) and
    API router: build a MetaAnalyzer separately, call
    ``analyze_with_findings()``, then ``apply_meta_analysis_to_results()``.

    Uses Gemini via LiteLLM (``gemini/<model>`` prefix) with the same
    Google API key used for the LLMAnalyzer.

    Returns ``(meta_analysis_dict, enriched_findings)`` on success, or
    ``(None, original_findings)`` if meta-analysis is unavailable or fails.
    """
    api_key = getattr(settings, "google_api_key", None)
    if not api_key or not result.findings:
        return None, list(result.findings)

    try:
        from skill_scanner.core.analyzers import MetaAnalyzer
        from skill_scanner.core.analyzers.meta_analyzer import (
            apply_meta_analysis_to_results,
        )
        from skill_scanner.core.loader import SkillLoader
    except ImportError:
        logger.debug("MetaAnalyzer or dependencies not available — skipping")
        return None, list(result.findings)

    model = getattr(settings, "gemini_model", "gemini-2.0-flash")
    litellm_model = f"gemini/{model}"

    try:
        meta = MetaAnalyzer(model=litellm_model, api_key=api_key)
        skill = SkillLoader().load_skill(skill_dir)

        meta_result, stdout = _capture_stdout_during(
            lambda: asyncio.run(
                meta.analyze_with_findings(
                    skill=skill,
                    findings=result.findings,
                    analyzers_used=result.analyzers_used,
                )
            )
        )
        if stdout:
            logger.info("MetaAnalyzer stdout: {}", stdout[:500])

        enriched = apply_meta_analysis_to_results(
            original_findings=result.findings,
            meta_result=meta_result,
            skill=skill,
        )
        result.findings = enriched
        if "meta_analyzer" not in result.analyzers_used:
            result.analyzers_used.append("meta_analyzer")

        logger.info(
            "Meta-analysis complete: validated={} fp={} missed={}",
            len(meta_result.validated_findings),
            len(meta_result.false_positives),
            len(meta_result.missed_threats),
        )
        return meta_result.to_dict(), enriched
    except Exception:
        logger.opt(exception=True).warning("Meta-analysis failed — using scan results as-is")
        return None, list(result.findings)


def _find_skill_root(base: Path) -> Path:
    """Find the directory containing SKILL.md within an extracted archive.

    Handles both flat zips (SKILL.md at root) and nested zips
    (single subdirectory containing SKILL.md).
    """
    if (base / "SKILL.md").exists():
        return base
    subdirs = [d for d in base.iterdir() if d.is_dir()]
    for d in subdirs:
        if (d / "SKILL.md").exists():
            return d
    logger.warning(
        "SKILL.md not found in '{}' or its immediate subdirectories; using base directory as skill root fallback",
        base,
    )
    return base


def _safe_extract_zip(zf: zipfile.ZipFile, dest: str) -> None:
    """Extract zip members with path traversal protection.

    Rejects any member whose resolved path escapes the destination
    directory (e.g. via ``../`` or absolute paths).
    """
    dest_path = os.path.realpath(dest)
    for member in zf.namelist():
        member_path = os.path.realpath(os.path.join(dest, member))
        if not member_path.startswith(dest_path + os.sep) and member_path != dest_path:
            raise ValueError(f"Zip member '{member}' would escape extraction directory")
    zf.extractall(dest)


# ---------------------------------------------------------------------------
# Scan entry points
# ---------------------------------------------------------------------------


def _llm_configured(settings: Any) -> bool:
    """Return True if LLM analyzers would be enabled for these settings."""
    return bool(getattr(settings, "google_api_key", None))


def _check_llm_degradation(
    result: BridgeScanResult, *, llm_expected: bool, captured_stdout: str = ""
) -> BridgeScanResult:
    """Detect and flag silent LLM analyzer degradation.

    The Cisco scanner swallows LLM errors, prints them to stdout, and
    still reports ``llm_analyzer`` in ``analyzers_used``
    (see https://github.com/cisco-ai-defense/skill-scanner/issues/38).

    Detection uses captured stdout from the scanner run: the scanner
    ``print()``s error messages when LLM calls fail.  ``MetaAnalyzer``
    always returns empty through the standard ``analyze()`` API so its
    ``meta_analysis`` field is unreliable as a signal.
    """
    if not llm_expected:
        return result

    _ERROR_SIGNALS = ("error", "exception", "failed", "traceback")
    has_error_output = any(s in captured_stdout.lower() for s in _ERROR_SIGNALS)
    if not has_error_output:
        return result

    logger.warning(
        "LLM analyzer degradation detected: LLM analyzers were configured "
        "but scanner emitted error output to stdout. "
        "Scan result may be static-only (see cisco-ai-defense/skill-scanner#38)"
    )

    degradation_finding: dict[str, Any] = {
        "rule_id": "LLM_DEGRADED",
        "category": "scan_quality",
        "severity": "INFO",
        "title": "LLM analysis did not produce results",
        "description": (
            "The LLM and meta-analysis stages were configured but "
            "returned no output. This scan reflects static analysis "
            "only. The grade may undercount threats that require "
            "semantic understanding."
        ),
        "file_path": None,
        "line_number": None,
        "snippet": None,
        "remediation": (
            "Check server logs for LLM errors (API key, rate limits, "
            "schema compatibility). See "
            "https://github.com/cisco-ai-defense/skill-scanner/issues/38"
        ),
        "analyzer": "bridge",
        "aitech_code": None,
        "metadata": {},
    }

    findings = [*result.findings, degradation_finding]
    return BridgeScanResult(
        is_safe=result.is_safe,
        max_severity=result.max_severity,
        grade=result.grade,
        findings_count=len(findings),
        findings=findings,
        analyzers_used=result.analyzers_used,
        analyzability_score=result.analyzability_score,
        scan_duration_ms=result.scan_duration_ms,
        policy_name=result.policy_name,
        policy_fingerprint=result.policy_fingerprint,
        full_report=result.full_report,
        meta_analysis=result.meta_analysis,
    )


def _capture_stdout_during(fn: Any) -> tuple[Any, str]:
    """Run *fn()* while capturing anything the scanner ``print()``s."""
    buf = io.StringIO()
    old = sys.stdout
    try:
        sys.stdout = buf
        return fn(), buf.getvalue()
    finally:
        sys.stdout = old


def scan_skill_dir(skill_dir: Path, settings: Any) -> BridgeScanResult:
    """Scan an on-disk skill directory (used by crawler/tracker).

    Returns a BridgeScanResult with all fields populated.
    Wraps scanner errors so callers get a failing BridgeScanResult
    instead of an unhandled exception from the third-party library.
    """
    start = time.monotonic()
    llm_expected = _llm_configured(settings)

    try:
        scanner = _build_scanner(settings)
        result, stdout = _capture_stdout_during(lambda: scanner.scan_skill(skill_dir))
    except Exception:
        logger.opt(exception=True).error("skill-scanner crashed on {}", skill_dir)
        return _error_scan_result(int((time.monotonic() - start) * 1000))

    if stdout:
        logger.info("skill-scanner stdout on {}: {}", skill_dir, stdout[:500])

    meta_dict, _ = _run_meta_analysis(result, skill_dir, settings)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    bridge_result = _map_scan_result(result, elapsed_ms, meta_analysis_override=meta_dict)
    return _check_llm_degradation(bridge_result, llm_expected=llm_expected, captured_stdout=stdout)


def scan_skill_zip(zip_bytes: bytes, settings: Any) -> BridgeScanResult:
    """Extract a zip to a temp dir and scan (used by publish endpoint).

    Returns a BridgeScanResult with all fields populated.
    Wraps scanner errors so callers get a failing BridgeScanResult
    instead of an unhandled exception from the third-party library.
    """
    start = time.monotonic()
    llm_expected = _llm_configured(settings)

    try:
        with tempfile.TemporaryDirectory(prefix="skill_scan_") as tmp:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                _safe_extract_zip(zf, tmp)
            skill_dir = _find_skill_root(Path(tmp))
            scanner = _build_scanner(settings)
            result, stdout = _capture_stdout_during(lambda: scanner.scan_skill(skill_dir))

            if stdout:
                logger.info("skill-scanner stdout on zip: {}", stdout[:500])

            meta_dict, _ = _run_meta_analysis(result, skill_dir, settings)
    except Exception:
        logger.opt(exception=True).error("skill-scanner crashed on zip input")
        return _error_scan_result(int((time.monotonic() - start) * 1000))

    elapsed_ms = int((time.monotonic() - start) * 1000)
    bridge_result = _map_scan_result(result, elapsed_ms, meta_analysis_override=meta_dict)
    return _check_llm_degradation(bridge_result, llm_expected=llm_expected, captured_stdout=stdout)


# ---------------------------------------------------------------------------
# Result mapping
# ---------------------------------------------------------------------------


def _error_scan_result(elapsed_ms: int) -> BridgeScanResult:
    """Return a fail-closed BridgeScanResult when the scanner itself errors."""
    return BridgeScanResult(
        is_safe=False,
        max_severity="CRITICAL",
        grade="F",
        findings_count=1,
        findings=[
            {
                "rule_id": "SCANNER_ERROR",
                "category": "policy_violation",
                "severity": "CRITICAL",
                "title": "Scanner internal error",
                "description": "The skill-scanner failed to complete. The skill is rejected (fail-closed).",
                "file_path": None,
                "line_number": None,
                "snippet": None,
                "remediation": "Retry the publish. If it persists, contact the platform team.",
                "analyzer": "bridge",
                "aitech_code": None,
                "metadata": {},
            }
        ],
        analyzers_used=[],
        analyzability_score=None,
        scan_duration_ms=elapsed_ms,
        policy_name=None,
        policy_fingerprint=None,
        full_report={"error": "scanner_crashed"},
        meta_analysis=None,
    )


def _map_scan_result(
    result: Any, elapsed_ms: int, *, meta_analysis_override: dict | None = None
) -> BridgeScanResult:
    """Convert a skill-scanner ScanResult to a BridgeScanResult."""
    result_dict = result.to_dict()

    max_severity = str(getattr(result, "max_severity", "SAFE"))
    if hasattr(result.max_severity, "name"):
        max_severity = result.max_severity.name

    findings = []
    for f in getattr(result, "findings", []):
        finding_dict = f.to_dict() if hasattr(f, "to_dict") else {}
        severity = str(getattr(f, "severity", "INFO"))
        if hasattr(f.severity, "name"):
            severity = f.severity.name

        category = str(getattr(f, "category", ""))
        if hasattr(f.category, "value"):
            category = f.category.value

        findings.append(
            {
                "rule_id": getattr(f, "rule_id", ""),
                "category": category,
                "severity": severity,
                "title": getattr(f, "title", ""),
                "description": getattr(f, "description", None),
                "file_path": getattr(f, "file_path", None),
                "line_number": getattr(f, "line_number", None),
                "snippet": getattr(f, "snippet", None),
                "remediation": getattr(f, "remediation", None),
                "analyzer": getattr(f, "analyzer", None),
                "aitech_code": finding_dict.get("metadata", {}).get("aitech_code"),
                "metadata": finding_dict.get("metadata", {}),
            }
        )

    analyzers_used = result_dict.get("analyzers_used", [])
    scan_metadata = result_dict.get("scan_metadata", {})

    meta_analysis = (
        meta_analysis_override
        or result_dict.get("meta_analysis")
        or scan_metadata.get("meta_analysis")
    )

    grade = severity_to_grade(max_severity)

    logger.info(
        "Scan complete: is_safe={} max_severity={} grade={} findings={} analyzers={} duration={}ms",
        result.is_safe,
        max_severity,
        grade,
        len(findings),
        analyzers_used,
        elapsed_ms,
    )

    return BridgeScanResult(
        is_safe=result.is_safe,
        max_severity=max_severity,
        grade=grade,
        findings_count=len(findings),
        findings=findings,
        analyzers_used=analyzers_used,
        analyzability_score=result_dict.get("analyzability_score"),
        scan_duration_ms=elapsed_ms,
        policy_name=scan_metadata.get("policy_name", "balanced"),
        policy_fingerprint=scan_metadata.get("policy_fingerprint"),
        full_report=result_dict,
        meta_analysis=meta_analysis,
    )
