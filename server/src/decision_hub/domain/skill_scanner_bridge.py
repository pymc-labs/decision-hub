"""Adapter between cisco-ai-skill-scanner and dhub's publish pipeline.

Handles zip extraction, scanner configuration, result mapping, and
grade computation. All three code paths (publish endpoint, crawler,
tracker) call through this module instead of the old gauntlet.
"""

from __future__ import annotations

import io
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


def _build_scanner(settings: Any) -> Any:
    """Build a SkillScanner configured for Scenario C (full pipeline)."""
    from skill_scanner import SkillScanner
    from skill_scanner.core.analyzer_factory import build_analyzers
    from skill_scanner.core.scan_policy import ScanPolicy

    policy = ScanPolicy.from_preset("balanced")

    api_key = getattr(settings, "google_api_key", None)
    model = getattr(settings, "gemini_model", "gemini-2.0-flash")

    analyzers = build_analyzers(
        policy,
        use_behavioral=True,
        use_llm=bool(api_key),
        llm_model=model,
        llm_api_key=api_key,
    )

    return SkillScanner(analyzers=analyzers, policy=policy), policy


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
    return base


# ---------------------------------------------------------------------------
# Scan entry points
# ---------------------------------------------------------------------------


def scan_skill_dir(skill_dir: Path, settings: Any) -> BridgeScanResult:
    """Scan an on-disk skill directory (used by crawler/tracker).

    Returns a BridgeScanResult with all fields populated.
    """
    start = time.monotonic()

    scanner, policy = _build_scanner(settings)
    result = scanner.scan_skill(str(skill_dir))

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return _map_scan_result(result, policy, elapsed_ms)


def scan_skill_zip(zip_bytes: bytes, settings: Any) -> BridgeScanResult:
    """Extract a zip to a temp dir and scan (used by publish endpoint).

    Returns a BridgeScanResult with all fields populated.
    """
    start = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="skill_scan_") as tmp:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(tmp)
        skill_dir = _find_skill_root(Path(tmp))
        scanner, policy = _build_scanner(settings)
        result = scanner.scan_skill(str(skill_dir))

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return _map_scan_result(result, policy, elapsed_ms)


# ---------------------------------------------------------------------------
# Result mapping
# ---------------------------------------------------------------------------


def _map_scan_result(result: Any, policy: Any, elapsed_ms: int) -> BridgeScanResult:
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

        findings.append({
            "rule_id": getattr(f, "rule_id", ""),
            "category": str(getattr(f, "category", "")),
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
        })

    analyzers_used = result_dict.get("analyzers_used", [])
    analyzability_score = result_dict.get("analyzability_score")

    meta_analysis = result_dict.get("meta_analysis") or result_dict.get("scan_metadata", {}).get("meta_analysis")

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
        analyzability_score=analyzability_score,
        scan_duration_ms=elapsed_ms,
        policy_name=getattr(policy, "name", "balanced"),
        policy_fingerprint=result_dict.get("scan_metadata", {}).get("policy_fingerprint"),
        full_report=result_dict,
        meta_analysis=meta_analysis,
    )
