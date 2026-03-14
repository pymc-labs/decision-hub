"""Tests for the skill_scanner_bridge module.

These tests mock the scanner library so they run without API keys or
the cisco-ai-skill-scanner package installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

from decision_hub.domain.skill_scanner_bridge import (
    _error_result,
    _find_skill_root,
    _map_findings,
    scan_skill_zip,
    store_scan_result,
)

# ---------------------------------------------------------------------------
# Helpers: Fake scanner types
# ---------------------------------------------------------------------------


class FakeSeverity:
    def __init__(self, value: str):
        self.value = value
        self.name = value


class FakeCategory:
    def __init__(self, value: str):
        self.value = value


@dataclass
class FakeFinding:
    rule_id: str = "TEST_RULE"
    category: Any = field(default_factory=lambda: FakeCategory("command_injection"))
    severity: Any = field(default_factory=lambda: FakeSeverity("MEDIUM"))
    title: str = "Test finding"
    description: str = "A test finding"
    file_path: str | None = "scripts/test.py"
    line_number: int | None = 42
    snippet: str | None = "os.system('rm -rf /')"
    remediation: str | None = "Don't do that"
    analyzer: str | None = "static"
    metadata: dict = field(default_factory=dict)


@dataclass
class FakeScanResult:
    skill_name: str = "test-skill"
    skill_directory: str = "/tmp/test"
    findings: list = field(default_factory=list)
    scan_duration_seconds: float = 1.5
    analyzers_used: list = field(default_factory=lambda: ["static", "behavioral"])
    analyzers_failed: list = field(default_factory=list)
    analyzability_score: float | None = 95.0
    analyzability_details: dict | None = None
    scan_metadata: dict | None = None

    @property
    def is_safe(self) -> bool:
        return not any(f.severity.value in ("CRITICAL", "HIGH") for f in self.findings)

    @property
    def max_severity(self) -> FakeSeverity:
        if not self.findings:
            return FakeSeverity("SAFE")
        order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
        worst = min(self.findings, key=lambda f: order.get(f.severity.value, 5))
        return worst.severity

    def to_dict(self) -> dict:
        return {
            "skill_name": self.skill_name,
            "is_safe": self.is_safe,
            "max_severity": self.max_severity.value,
            "findings": [],
            "analyzers_used": self.analyzers_used,
        }


# ---------------------------------------------------------------------------
# Tests: _map_findings
# ---------------------------------------------------------------------------


class TestMapFindings:
    def test_empty_list(self):
        assert _map_findings([]) == []

    def test_maps_finding_fields(self):
        f = FakeFinding()
        result = _map_findings([f])
        assert len(result) == 1
        mapped = result[0]
        assert mapped["rule_id"] == "TEST_RULE"
        assert mapped["category"] == "command_injection"
        assert mapped["severity"] == "MEDIUM"
        assert mapped["title"] == "Test finding"
        assert mapped["file_path"] == "scripts/test.py"
        assert mapped["line_number"] == 42
        assert mapped["analyzer"] == "static"

    def test_maps_meta_enrichment(self):
        f = FakeFinding(
            metadata={
                "meta_false_positive": True,
                "meta_confidence": "HIGH",
                "meta_priority": 1,
                "meta_reason": "keyword in comment",
            }
        )
        result = _map_findings([f])
        mapped = result[0]
        assert mapped["is_false_positive"] is True
        assert mapped["meta_confidence"] == "HIGH"
        assert mapped["meta_priority"] == 1

    def test_handles_missing_optional_fields(self):
        f = FakeFinding(
            file_path=None,
            line_number=None,
            snippet=None,
            remediation=None,
            analyzer=None,
        )
        result = _map_findings([f])
        mapped = result[0]
        assert mapped["file_path"] is None
        assert mapped["line_number"] is None


# ---------------------------------------------------------------------------
# Tests: _error_result
# ---------------------------------------------------------------------------


class TestErrorResult:
    def test_returns_fail_closed_dict(self):
        result = _error_result(500)
        assert result["is_safe"] is False
        assert result["max_severity"] == "CRITICAL"
        assert result["findings_count"] == 1
        assert result["scan_duration_ms"] == 500
        assert result["findings"][0]["rule_id"] == "SCANNER_ERROR"
        assert result["findings"][0]["severity"] == "CRITICAL"

    def test_has_all_required_keys(self):
        result = _error_result(0)
        required = {
            "is_safe",
            "max_severity",
            "findings_count",
            "analyzers_used",
            "analyzers_failed",
            "full_report",
            "meta_analysis",
            "scan_metadata",
            "findings",
            "scanner_version",
            "scan_duration_ms",
        }
        assert required.issubset(result.keys())


# ---------------------------------------------------------------------------
# Tests: _find_skill_root
# ---------------------------------------------------------------------------


class TestFindSkillRoot:
    def test_skill_md_at_root(self, tmp_path):
        (tmp_path / "SKILL.md").touch()
        assert _find_skill_root(tmp_path) == tmp_path

    def test_skill_md_in_subdir(self, tmp_path):
        sub = tmp_path / "my-skill"
        sub.mkdir()
        (sub / "SKILL.md").touch()
        assert _find_skill_root(tmp_path) == sub

    def test_fallback_to_base(self, tmp_path):
        assert _find_skill_root(tmp_path) == tmp_path


# ---------------------------------------------------------------------------
# Tests: scan_skill_zip (mocked)
# ---------------------------------------------------------------------------


class TestScanSkillZip:
    @patch("decision_hub.domain.skill_scanner_bridge._build_scanner")
    def test_returns_result_dict_on_success(self, mock_build):
        fake_result = FakeScanResult(findings=[FakeFinding()])
        mock_scanner = MagicMock()
        mock_scanner.scan_skill.return_value = fake_result

        mock_build.return_value = (mock_scanner, MagicMock())

        # Create a minimal zip with SKILL.md
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: test\ndescription: test\n---\n# Test")
        zip_bytes = buf.getvalue()

        settings = SimpleNamespace(
            google_api_key="",
            gemini_model="test",
            cisco_scanner_policy="balanced",
            enable_cisco_scanner=True,
        )

        result = scan_skill_zip(zip_bytes, settings)

        assert result["is_safe"] is True  # MEDIUM doesn't make unsafe
        assert result["max_severity"] == "MEDIUM"
        assert result["findings_count"] == 1
        assert len(result["findings"]) == 1
        assert result["findings"][0]["rule_id"] == "TEST_RULE"

    @patch("decision_hub.domain.skill_scanner_bridge._build_scanner")
    def test_returns_error_on_crash(self, mock_build):
        mock_build.side_effect = RuntimeError("scanner crashed")

        settings = SimpleNamespace(
            google_api_key="",
            gemini_model="test",
            cisco_scanner_policy="balanced",
            enable_cisco_scanner=True,
        )

        result = scan_skill_zip(b"not a zip", settings)
        assert result["is_safe"] is False
        assert result["max_severity"] == "CRITICAL"
        assert result["findings"][0]["rule_id"] == "SCANNER_ERROR"

    @patch("decision_hub.domain.skill_scanner_bridge._build_scanner")
    def test_safe_skill_no_findings(self, mock_build):
        fake_result = FakeScanResult(findings=[])
        mock_scanner = MagicMock()
        mock_scanner.scan_skill.return_value = fake_result
        mock_build.return_value = (mock_scanner, MagicMock())

        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: safe\ndescription: safe\n---\n")
        zip_bytes = buf.getvalue()

        settings = SimpleNamespace(
            google_api_key="",
            gemini_model="test",
            cisco_scanner_policy="balanced",
            enable_cisco_scanner=True,
        )

        result = scan_skill_zip(zip_bytes, settings)
        assert result["is_safe"] is True
        assert result["max_severity"] == "SAFE"
        assert result["findings_count"] == 0


# ---------------------------------------------------------------------------
# Tests: store_scan_result (mocked DB)
# ---------------------------------------------------------------------------


class TestStoreScanResult:
    @patch("decision_hub.domain.skill_scanner_bridge.insert_scan_findings")
    @patch("decision_hub.domain.skill_scanner_bridge.insert_scan_report")
    def test_stores_report_and_findings(self, mock_report, mock_findings):
        mock_report.return_value = SimpleNamespace(id=uuid4())

        scan_data = {
            "is_safe": True,
            "max_severity": "LOW",
            "findings_count": 1,
            "analyzers_used": ["static"],
            "analyzers_failed": [],
            "findings": [{"rule_id": "R1", "category": "c", "severity": "LOW", "title": "t"}],
            "full_report": {},
            "meta_analysis": None,
            "scan_metadata": None,
            "analyzability_score": 98.0,
            "analyzability_details": None,
            "meta_verdict": "SAFE",
            "meta_risk_level": "SAFE",
            "meta_summary": "Looks good",
            "meta_top_priority": None,
            "meta_correlations": None,
            "meta_recommendations": None,
            "meta_false_positive_count": 0,
            "scanner_version": "2.0.3",
            "scanner_model": "gemini/test",
            "policy_name": "balanced",
            "scan_duration_ms": 1500,
        }

        conn = MagicMock()
        report_id = store_scan_result(
            conn,
            scan_data,
            version_id=uuid4(),
            org_slug="test",
            skill_name="skill",
            semver="1.0.0",
        )

        mock_report.assert_called_once()
        mock_findings.assert_called_once()
        assert report_id == mock_report.return_value.id

    @patch("decision_hub.domain.skill_scanner_bridge.insert_scan_findings")
    @patch("decision_hub.domain.skill_scanner_bridge.insert_scan_report")
    def test_skips_findings_when_empty(self, mock_report, mock_findings):
        mock_report.return_value = SimpleNamespace(id=uuid4())

        scan_data = _error_result(100)
        scan_data["findings"] = []

        conn = MagicMock()
        store_scan_result(
            conn,
            scan_data,
            version_id=None,
            org_slug="test",
            skill_name="s",
            semver="1.0.0",
        )

        mock_findings.assert_not_called()
