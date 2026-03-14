"""Adapter between cisco-ai-skill-scanner (>=2.0) and dhub's publish pipeline.

Runs the Cisco scanner alongside the gauntlet and maps results for storage.
No monkey patches — all upstream bugs fixed in 2.0.0+.
Thread-safe — no global state mutation.

The scanner never affects publish/reject decisions. Results are stored
in scan_reports/scan_findings for display in the UI.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import io
import os
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy.engine import Connection

from decision_hub.infra.database import insert_scan_findings, insert_scan_report
from decision_hub.settings import Settings


def _get_scanner_version() -> str | None:
    try:
        return importlib.metadata.version("cisco-ai-skill-scanner")
    except importlib.metadata.PackageNotFoundError:
        return None


def _safe_extract_zip(zf: zipfile.ZipFile, dest: str) -> None:
    """Extract zip members with path traversal protection."""
    dest_path = os.path.realpath(dest)
    for member in zf.namelist():
        member_path = os.path.realpath(os.path.join(dest, member))
        if not member_path.startswith(dest_path + os.sep) and member_path != dest_path:
            raise ValueError(f"Zip member '{member}' would escape extraction directory")
    zf.extractall(dest)


def _find_skill_root(base: Path) -> Path:
    """Find the directory containing SKILL.md within an extracted archive."""
    if (base / "SKILL.md").exists():
        return base
    for d in base.iterdir():
        if d.is_dir() and (d / "SKILL.md").exists():
            return d
    return base


def _build_scanner(settings: Settings) -> tuple[Any, Any]:
    """Build a SkillScanner with all analyzers and a ScanPolicy.

    Returns (scanner, policy).
    """
    from skill_scanner import SkillScanner
    from skill_scanner.core.analyzer_factory import build_analyzers
    from skill_scanner.core.scan_policy import ScanPolicy

    policy = ScanPolicy.from_preset(settings.cisco_scanner_policy)

    analyzers = build_analyzers(
        policy,
        use_behavioral=True,
        use_llm=bool(settings.google_api_key),
        llm_model=f"gemini/{settings.gemini_model}" if settings.google_api_key else None,
        llm_api_key=settings.google_api_key or None,
        use_trigger=True,
        llm_max_tokens=16384,
    )

    scanner = SkillScanner(analyzers=analyzers, policy=policy)
    return scanner, policy


def _run_meta_analysis(
    result: Any, skill_dir: Path, settings: Settings, policy: Any
) -> tuple[Any | None, Exception | None]:
    """Run MetaAnalyzer as a post-processing step.

    Returns (meta_result, error). On success error is None.
    On failure meta_result is None and error is the exception.
    """
    if not settings.google_api_key or not result.findings:
        return None, None

    try:
        from skill_scanner.core.analyzers.meta_analyzer import (
            MetaAnalyzer,
            apply_meta_analysis_to_results,
        )
        from skill_scanner.core.loader import SkillLoader
    except ImportError:
        return None, None

    try:
        meta = MetaAnalyzer(
            model=f"gemini/{settings.gemini_model}",
            api_key=settings.google_api_key,
            policy=policy,
        )

        loader_max = policy.file_limits.max_loader_file_size_bytes
        skill = SkillLoader(max_file_size_bytes=loader_max).load_skill(skill_dir)

        meta_result = asyncio.run(
            meta.analyze_with_findings(
                skill=skill,
                findings=result.findings,
                analyzers_used=result.analyzers_used,
            )
        )

        result.findings = apply_meta_analysis_to_results(
            original_findings=result.findings,
            meta_result=meta_result,
            skill=skill,
        )
        if "meta_analyzer" not in result.analyzers_used:
            result.analyzers_used.append("meta_analyzer")

        return meta_result, None
    except (ImportError, MemoryError):
        raise
    except Exception as exc:
        return None, exc


def _map_findings(findings: list[Any]) -> list[dict]:
    """Convert scanner Finding objects to dicts for storage."""
    mapped: list[dict] = []
    for f in findings:
        severity = f.severity.value if hasattr(f.severity, "value") else str(f.severity)
        category = f.category.value if hasattr(f.category, "value") else str(f.category)
        meta = f.metadata if hasattr(f, "metadata") else {}

        mapped.append(
            {
                "rule_id": f.rule_id,
                "category": category,
                "severity": severity,
                "title": f.title,
                "description": f.description,
                "file_path": f.file_path,
                "line_number": f.line_number,
                "snippet": getattr(f, "snippet", None),
                "remediation": getattr(f, "remediation", None),
                "analyzer": getattr(f, "analyzer", None),
                "is_false_positive": meta.get("meta_false_positive"),
                "meta_confidence": meta.get("meta_confidence"),
                "meta_priority": meta.get("meta_priority"),
                "metadata": meta,
            }
        )
    return mapped


def scan_skill_zip(zip_bytes: bytes, settings: Settings) -> dict:
    """Scan a skill zip and return a dict ready for insert_scan_report.

    Returns a dict with all fields needed by insert_scan_report plus
    a "findings" list for insert_scan_findings.

    Scanner errors are caught and returned as a fail-closed error result.
    """
    start = time.monotonic()

    try:
        scanner, policy = _build_scanner(settings)
    except Exception:
        logger.opt(exception=True).error("Failed to build skill scanner")
        return _error_result(int((time.monotonic() - start) * 1000))

    try:
        with tempfile.TemporaryDirectory(prefix="skill_scan_") as tmp:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                _safe_extract_zip(zf, tmp)
            skill_dir = _find_skill_root(Path(tmp))

            result = scanner.scan_skill(skill_dir)

            meta_result, meta_error = _run_meta_analysis(result, skill_dir, settings, policy)
            if meta_error is not None:
                logger.opt(exception=meta_error).warning("Meta-analysis failed — using scan results as-is")
    except (ImportError, MemoryError, zipfile.BadZipFile, ValueError):
        raise
    except Exception:
        logger.opt(exception=True).error("skill-scanner crashed on zip input")
        return _error_result(int((time.monotonic() - start) * 1000))

    elapsed_ms = int((time.monotonic() - start) * 1000)
    max_severity = result.max_severity.value if hasattr(result.max_severity, "value") else str(result.max_severity)
    findings = _map_findings(result.findings)

    overall_risk: dict[str, Any] = {}
    if meta_result is not None:
        overall_risk = getattr(meta_result, "overall_risk_assessment", {}) or {}

    report_dict: dict[str, Any] = {
        "is_safe": result.is_safe,
        "max_severity": max_severity,
        "findings_count": len(findings),
        "analyzers_used": list(result.analyzers_used),
        "analyzers_failed": list(getattr(result, "analyzers_failed", []) or []),
        "analyzability_score": result.analyzability_score,
        "analyzability_details": (result.analyzability_details if hasattr(result, "analyzability_details") else None),
        "meta_verdict": overall_risk.get("skill_verdict"),
        "meta_risk_level": overall_risk.get("risk_level"),
        "meta_summary": overall_risk.get("summary"),
        "meta_top_priority": overall_risk.get("top_priority"),
        "meta_correlations": (meta_result.correlations if meta_result and meta_result.correlations else None),
        "meta_recommendations": (meta_result.recommendations if meta_result and meta_result.recommendations else None),
        "meta_false_positive_count": (len(meta_result.false_positives) if meta_result else None),
        "scanner_version": _get_scanner_version(),
        "scanner_model": f"gemini/{settings.gemini_model}" if settings.google_api_key else None,
        "policy_name": settings.cisco_scanner_policy,
        "scan_duration_ms": elapsed_ms,
        "full_report": result.to_dict(),
        "meta_analysis": meta_result.to_dict() if meta_result else None,
        "scan_metadata": result.scan_metadata,
        "findings": findings,
    }

    logger.info(
        "Cisco scan complete: safe={} max_severity={} meta_verdict={} findings={} "
        "fp_filtered={} analyzers={} duration={}ms",
        result.is_safe,
        max_severity,
        overall_risk.get("skill_verdict"),
        len(findings),
        len(meta_result.false_positives) if meta_result else 0,
        result.analyzers_used,
        elapsed_ms,
    )

    return report_dict


def _error_result(elapsed_ms: int) -> dict:
    """Return a fail-closed result dict when the scanner itself errors."""
    return {
        "is_safe": False,
        "max_severity": "CRITICAL",
        "findings_count": 1,
        "analyzers_used": [],
        "analyzers_failed": [{"analyzer": "bridge", "error": "scanner_crashed"}],
        "analyzability_score": None,
        "analyzability_details": None,
        "meta_verdict": None,
        "meta_risk_level": None,
        "meta_summary": None,
        "meta_top_priority": None,
        "meta_correlations": None,
        "meta_recommendations": None,
        "meta_false_positive_count": None,
        "scanner_version": _get_scanner_version(),
        "scanner_model": None,
        "policy_name": None,
        "scan_duration_ms": elapsed_ms,
        "full_report": {"error": "scanner_crashed"},
        "meta_analysis": None,
        "scan_metadata": None,
        "findings": [
            {
                "rule_id": "SCANNER_ERROR",
                "category": "policy_violation",
                "severity": "CRITICAL",
                "title": "Scanner internal error",
                "description": "The skill-scanner failed to complete. Result is fail-closed.",
                "file_path": None,
                "line_number": None,
                "snippet": None,
                "remediation": "Retry the publish. If it persists, contact the platform team.",
                "analyzer": "bridge",
                "is_false_positive": False,
                "meta_confidence": None,
                "meta_priority": None,
                "metadata": {},
            }
        ],
    }


def store_scan_result(
    conn: Connection,
    scan_data: dict,
    *,
    version_id: UUID | None,
    org_slug: str,
    skill_name: str,
    semver: str,
) -> UUID:
    """Store a scan result (report + findings) in the database.

    Returns the scan report ID.
    """
    findings = scan_data.pop("findings", [])

    report = insert_scan_report(
        conn,
        version_id=version_id,
        org_slug=org_slug,
        skill_name=skill_name,
        semver=semver,
        **scan_data,
    )

    if findings:
        insert_scan_findings(conn, report.id, findings)

    return report.id
