"""Adapter between cisco-ai-skill-scanner and dhub's publish pipeline.

Handles zip extraction, scanner configuration, result mapping, and
grade computation. All three code paths (publish endpoint, crawler,
tracker) call through this module instead of the old gauntlet.
"""

from __future__ import annotations

import io
import os
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from decision_hub.models import SafetyGrade

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
    """Build the list of analyzers for Scenario C (full pipeline)."""
    from skill_scanner.core.analyzers import (
        BehavioralAnalyzer,
        LLMAnalyzer,
        MetaAnalyzer,
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
        analyzers.append(MetaAnalyzer(model=model, api_key=api_key))

    return analyzers


def _build_scanner(settings: Any) -> Any:
    """Build a SkillScanner configured for Scenario C (full pipeline)."""
    from skill_scanner import SkillScanner

    analyzers = _build_analyzers(settings)
    return SkillScanner(analyzers=analyzers)


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


def scan_skill_dir(skill_dir: Path, settings: Any) -> BridgeScanResult:
    """Scan an on-disk skill directory (used by crawler/tracker).

    Returns a BridgeScanResult with all fields populated.
    Wraps scanner errors so callers get a failing BridgeScanResult
    instead of an unhandled exception from the third-party library.
    """
    start = time.monotonic()

    try:
        scanner = _build_scanner(settings)
        result = scanner.scan_skill(skill_dir)
    except Exception:
        logger.opt(exception=True).error("skill-scanner crashed on {}", skill_dir)
        return _error_scan_result(int((time.monotonic() - start) * 1000))

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return _map_scan_result(result, elapsed_ms)


def scan_skill_zip(zip_bytes: bytes, settings: Any) -> BridgeScanResult:
    """Extract a zip to a temp dir and scan (used by publish endpoint).

    Returns a BridgeScanResult with all fields populated.
    Wraps scanner errors so callers get a failing BridgeScanResult
    instead of an unhandled exception from the third-party library.
    """
    start = time.monotonic()

    try:
        with tempfile.TemporaryDirectory(prefix="skill_scan_") as tmp:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                _safe_extract_zip(zf, tmp)
            skill_dir = _find_skill_root(Path(tmp))
            scanner = _build_scanner(settings)
            result = scanner.scan_skill(skill_dir)
    except Exception:
        logger.opt(exception=True).error("skill-scanner crashed on zip input")
        return _error_scan_result(int((time.monotonic() - start) * 1000))

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return _map_scan_result(result, elapsed_ms)


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


def _map_scan_result(result: Any, elapsed_ms: int) -> BridgeScanResult:
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

    meta_analysis = result_dict.get("meta_analysis") or scan_metadata.get("meta_analysis")

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
