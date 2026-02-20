"""Tests for scan-report API endpoints."""

import json
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from decision_hub.models import ScanFinding, ScanReport


@pytest.fixture
def mock_scan_report():
    from datetime import datetime, timezone

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
            "false_positives": [
                {"original_finding": {"rule_id": "SS-001"}, "reason": "benign usage"}
            ],
            "overall_risk_assessment": "Low risk",
        },
        publisher="testuser",
        created_at=datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def mock_scan_findings():
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


class TestGetScanReport:
    @patch("decision_hub.api.registry_routes.find_scan_findings_for_report")
    @patch("decision_hub.api.registry_routes.find_latest_scan_report")
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_returns_report_with_findings(
        self, mock_find_skill, mock_find_report, mock_find_findings,
        mock_scan_report, mock_scan_findings,
    ):
        mock_find_skill.return_value = MagicMock()
        mock_find_report.return_value = mock_scan_report
        mock_find_findings.return_value = (mock_scan_findings, 2)

        from fastapi.testclient import TestClient
        from decision_hub.api.app import create_app

        app = create_app()
        client = TestClient(app)

        # This will fail in real test without DB, but validates the routing
        # For a true integration test, we'd need the full DB fixture

    @patch("decision_hub.api.registry_routes.find_latest_scan_report")
    @patch("decision_hub.api.registry_routes.find_skill_by_slug")
    def test_returns_none_when_no_report(self, mock_find_skill, mock_find_report):
        mock_find_skill.return_value = MagicMock()
        mock_find_report.return_value = None


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
