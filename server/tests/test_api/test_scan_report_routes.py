"""Tests for scan-report API endpoints."""

from datetime import UTC, datetime
from uuid import uuid4

from decision_hub.models import ScanFinding, ScanReport


def _make_scan_report():
    return ScanReport(
        id=uuid4(),
        version_id=uuid4(),
        org_slug="test-org",
        skill_name="test-skill",
        semver="1.0.0",
        is_safe=True,
        max_severity="LOW",
        grade="A",
        findings_count=2,
        analyzers_used=["static", "behavioral", "llm", "meta"],
        analyzability_score=95.0,
        scan_duration_ms=5000,
        policy_name="balanced",
        policy_fingerprint="abc123",
        full_report={
            "findings": [
                {"rule_id": "SS-001", "title": "Minor issue"},
                {"rule_id": "SS-002", "title": "Info finding"},
            ],
            "scan_metadata": {"policy_fingerprint": "abc123"},
        },
        meta_analysis={
            "validated_findings": [],
            "false_positives": [{"original_finding": {"rule_id": "SS-001"}, "reason": "benign usage"}],
            "overall_risk_assessment": "Low risk",
        },
        publisher="testuser",
        created_at=datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 2, 20, 12, 0, 0, tzinfo=UTC),
    )


def _make_scan_findings():
    return [
        ScanFinding(
            id=uuid4(),
            report_id=uuid4(),
            rule_id="SS-CMD-001",
            category="command_injection",
            severity="LOW",
            title="Subprocess usage",
            description="Uses subprocess.run",
            file_path="main.py",
            line_number=10,
            snippet="subprocess.run(['ls'])",
            remediation="Use allowlist",
            analyzer="static",
            aitech_code="AITech-9.1",
        ),
        ScanFinding(
            id=uuid4(),
            report_id=uuid4(),
            rule_id="SS-INFO-001",
            category="policy_violation",
            severity="INFO",
            title="Informational",
            description="Minor note",
        ),
    ]


class TestScanReportFixtures:
    def test_scan_report_fixture(self):
        report = _make_scan_report()
        assert report.grade == "A"
        assert report.is_safe is True
        assert report.findings_count == 2

    def test_scan_findings_fixture(self):
        findings = _make_scan_findings()
        assert len(findings) == 2
        assert findings[0].rule_id == "SS-CMD-001"


class TestScanReportModels:
    """Test that scan report response models serialize correctly."""

    def test_scan_finding_response_fields(self):
        from decision_hub.api.registry_routes import ScanFindingResponse

        resp = ScanFindingResponse(
            rule_id="SS-001",
            category="command_injection",
            severity="HIGH",
            title="Test finding",
            description="A test",
            file_path="main.py",
            line_number=5,
            snippet="code",
            remediation="Fix it",
            analyzer="static",
            aitech_code="AITech-9.1",
        )
        d = resp.model_dump()
        assert d["rule_id"] == "SS-001"
        assert d["severity"] == "HIGH"
        assert d["aitech_code"] == "AITech-9.1"
        assert d["meta_false_positive"] is None
        assert d["meta_confidence"] is None
        assert d["meta_reason"] is None

    def test_scan_finding_response_with_meta_fields(self):
        from decision_hub.api.registry_routes import ScanFindingResponse

        resp = ScanFindingResponse(
            rule_id="SS-002",
            category="prompt_injection",
            severity="MEDIUM",
            title="External file reference",
            description="References external file",
            file_path="SKILL.md",
            line_number=3,
            snippet=None,
            remediation=None,
            analyzer="llm_analyzer",
            aitech_code=None,
            meta_false_positive=True,
            meta_confidence="high",
            meta_reason="Benign filename reference in documentation context",
        )
        d = resp.model_dump()
        assert d["meta_false_positive"] is True
        assert d["meta_confidence"] == "high"
        assert d["meta_reason"] == "Benign filename reference in documentation context"

    def test_scan_report_summary_response_fields(self):
        from decision_hub.api.registry_routes import ScanReportSummaryResponse

        resp = ScanReportSummaryResponse(
            id="test-id",
            org_slug="test-org",
            skill_name="test-skill",
            semver="1.0.0",
            grade="A",
            is_safe=True,
            max_severity="LOW",
            findings_count=0,
            analyzers_used=["static"],
            analyzability_score=100.0,
            scan_duration_ms=500,
            created_at="2026-02-20T12:00:00Z",
            findings=[],
            findings_total=0,
            findings_page=1,
            findings_page_size=20,
        )
        d = resp.model_dump()
        assert d["grade"] == "A"
        assert d["is_safe"] is True
        assert d["analyzers_used"] == ["static"]
        assert d["meta_risk_level"] is None
        assert d["meta_verdict"] is None

    def test_scan_report_summary_with_meta_fields(self):
        from decision_hub.api.registry_routes import ScanReportSummaryResponse

        resp = ScanReportSummaryResponse(
            id="test-id",
            org_slug="test-org",
            skill_name="test-skill",
            semver="1.0.0",
            grade="B",
            is_safe=True,
            max_severity="LOW",
            findings_count=3,
            analyzers_used=["static", "llm_analyzer", "meta_analyzer"],
            analyzability_score=90.0,
            scan_duration_ms=3000,
            created_at="2026-02-20T12:00:00Z",
            findings=[],
            findings_total=3,
            findings_page=1,
            findings_page_size=20,
            meta_risk_level="LOW",
            meta_verdict="SAFE",
            meta_verdict_reasoning="All findings are low severity or false positives",
            meta_validated_count=2,
            meta_false_positive_count=1,
        )
        d = resp.model_dump()
        assert d["meta_risk_level"] == "LOW"
        assert d["meta_verdict"] == "SAFE"
        assert d["meta_verdict_reasoning"] == "All findings are low severity or false positives"
        assert d["meta_validated_count"] == 2
        assert d["meta_false_positive_count"] == 1
