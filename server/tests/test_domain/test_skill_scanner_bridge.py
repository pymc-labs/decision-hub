"""Tests for domain/skill_scanner_bridge.py — the adapter between skill-scanner and dhub."""

from unittest.mock import MagicMock, patch

import pytest

from decision_hub.domain.skill_scanner_bridge import (
    BridgeScanResult,
    _find_skill_root,
    _map_scan_result,
    severity_to_grade,
)


class TestSeverityToGrade:
    def test_critical_is_f(self):
        assert severity_to_grade("CRITICAL") == "F"

    def test_high_is_f(self):
        assert severity_to_grade("HIGH") == "F"

    def test_medium_is_c(self):
        assert severity_to_grade("MEDIUM") == "C"

    def test_low_is_a(self):
        assert severity_to_grade("LOW") == "A"

    def test_info_is_a(self):
        assert severity_to_grade("INFO") == "A"

    def test_safe_is_a(self):
        assert severity_to_grade("SAFE") == "A"

    def test_unknown_defaults_to_a(self):
        assert severity_to_grade("UNKNOWN") == "A"


class TestFindSkillRoot:
    def test_skill_md_at_root(self, tmp_path):
        (tmp_path / "SKILL.md").write_text("---\nname: test\n---\n")
        assert _find_skill_root(tmp_path) == tmp_path

    def test_skill_md_in_subdirectory(self, tmp_path):
        sub = tmp_path / "my-skill"
        sub.mkdir()
        (sub / "SKILL.md").write_text("---\nname: test\n---\n")
        assert _find_skill_root(tmp_path) == sub

    def test_no_skill_md_returns_base(self, tmp_path):
        (tmp_path / "README.md").write_text("hello")
        assert _find_skill_root(tmp_path) == tmp_path


class TestMapScanResult:
    def _make_mock_result(
        self,
        *,
        is_safe: bool = True,
        max_severity_name: str = "LOW",
        findings: list | None = None,
    ) -> MagicMock:
        """Create a mock ScanResult with the expected attributes."""
        result = MagicMock()
        result.is_safe = is_safe

        sev = MagicMock()
        sev.name = max_severity_name
        result.max_severity = sev

        if findings is None:
            findings = []
        result.findings = findings

        result.to_dict.return_value = {
            "is_safe": is_safe,
            "max_severity": max_severity_name,
            "findings": [],
            "analyzers_used": ["static", "behavioral"],
            "analyzability_score": 95.0,
            "scan_metadata": {"policy_fingerprint": "abc123"},
        }
        return result

    def test_safe_result_maps_to_grade_a(self):
        mock_result = self._make_mock_result(is_safe=True, max_severity_name="LOW")
        policy = MagicMock()
        policy.name = "balanced"

        bridge_result = _map_scan_result(mock_result, policy, elapsed_ms=100)

        assert bridge_result.grade == "A"
        assert bridge_result.is_safe is True
        assert bridge_result.max_severity == "LOW"
        assert bridge_result.scan_duration_ms == 100
        assert bridge_result.policy_name == "balanced"

    def test_critical_result_maps_to_grade_f(self):
        mock_result = self._make_mock_result(is_safe=False, max_severity_name="CRITICAL")
        policy = MagicMock()
        policy.name = "balanced"

        bridge_result = _map_scan_result(mock_result, policy, elapsed_ms=5000)

        assert bridge_result.grade == "F"
        assert bridge_result.is_safe is False
        assert bridge_result.max_severity == "CRITICAL"

    def test_medium_result_maps_to_grade_c(self):
        mock_result = self._make_mock_result(is_safe=True, max_severity_name="MEDIUM")
        policy = MagicMock()
        policy.name = "balanced"

        bridge_result = _map_scan_result(mock_result, policy, elapsed_ms=200)

        assert bridge_result.grade == "C"

    def test_findings_are_extracted(self):
        finding = MagicMock()
        finding.rule_id = "SS-CMD-001"
        finding.category = "command_injection"
        sev = MagicMock()
        sev.name = "HIGH"
        finding.severity = sev
        finding.title = "Subprocess usage"
        finding.description = "Uses subprocess.run"
        finding.file_path = "main.py"
        finding.line_number = 10
        finding.snippet = "subprocess.run(['ls'])"
        finding.remediation = "Use allowlist"
        finding.analyzer = "static"
        finding.to_dict.return_value = {"metadata": {"aitech_code": "AITech-9.1"}}

        mock_result = self._make_mock_result(
            is_safe=False,
            max_severity_name="HIGH",
            findings=[finding],
        )
        policy = MagicMock()
        policy.name = "balanced"

        bridge_result = _map_scan_result(mock_result, policy, elapsed_ms=300)

        assert bridge_result.findings_count == 1
        f = bridge_result.findings[0]
        assert f["rule_id"] == "SS-CMD-001"
        assert f["category"] == "command_injection"
        assert f["severity"] == "HIGH"
        assert f["title"] == "Subprocess usage"
        assert f["file_path"] == "main.py"
        assert f["aitech_code"] == "AITech-9.1"

    def test_full_report_preserved(self):
        mock_result = self._make_mock_result()
        policy = MagicMock()
        policy.name = "balanced"

        bridge_result = _map_scan_result(mock_result, policy, elapsed_ms=50)

        assert bridge_result.full_report is not None
        assert bridge_result.full_report["analyzers_used"] == ["static", "behavioral"]
        assert bridge_result.analyzability_score == 95.0
