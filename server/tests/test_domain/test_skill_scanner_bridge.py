"""Tests for domain/skill_scanner_bridge.py — the adapter between skill-scanner and dhub."""

import io
import zipfile
from unittest.mock import MagicMock

import pytest

from decision_hub.domain.skill_scanner_bridge import (
    _error_scan_result,
    _find_skill_root,
    _fix_gemini_union_types,
    _map_scan_result,
    _safe_extract_zip,
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

    def test_no_skill_md_returns_base_with_warning(self, tmp_path):
        (tmp_path / "README.md").write_text("hello")
        assert _find_skill_root(tmp_path) == tmp_path


class TestSafeExtractZip:
    def test_normal_zip_extracts(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: test\n---\n")
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            _safe_extract_zip(zf, str(tmp_path))
        assert (tmp_path / "SKILL.md").exists()

    def test_path_traversal_rejected(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../../etc/passwd", "malicious")
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf, pytest.raises(ValueError, match="would escape"):
            _safe_extract_zip(zf, str(tmp_path))


class TestErrorScanResult:
    def test_returns_grade_f(self):
        result = _error_scan_result(100)
        assert result.grade == "F"
        assert result.is_safe is False
        assert result.max_severity == "CRITICAL"
        assert result.findings_count == 1
        assert result.findings[0]["rule_id"] == "SCANNER_ERROR"


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
            "scan_metadata": {"policy_fingerprint": "abc123", "policy_name": "strict"},
        }
        return result

    def test_safe_result_maps_to_grade_a(self):
        mock_result = self._make_mock_result(is_safe=True, max_severity_name="LOW")

        bridge_result = _map_scan_result(mock_result, elapsed_ms=100)

        assert bridge_result.grade == "A"
        assert bridge_result.is_safe is True
        assert bridge_result.max_severity == "LOW"
        assert bridge_result.scan_duration_ms == 100
        assert bridge_result.policy_name == "strict"

    def test_critical_result_maps_to_grade_f(self):
        mock_result = self._make_mock_result(is_safe=False, max_severity_name="CRITICAL")

        bridge_result = _map_scan_result(mock_result, elapsed_ms=5000)

        assert bridge_result.grade == "F"
        assert bridge_result.is_safe is False
        assert bridge_result.max_severity == "CRITICAL"

    def test_medium_result_maps_to_grade_c(self):
        mock_result = self._make_mock_result(is_safe=True, max_severity_name="MEDIUM")

        bridge_result = _map_scan_result(mock_result, elapsed_ms=200)

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

        bridge_result = _map_scan_result(mock_result, elapsed_ms=300)

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

        bridge_result = _map_scan_result(mock_result, elapsed_ms=50)

        assert bridge_result.full_report is not None
        assert bridge_result.full_report["analyzers_used"] == ["static", "behavioral"]

    def test_analyzability_score_extracted(self):
        mock_result = self._make_mock_result()

        bridge_result = _map_scan_result(mock_result, elapsed_ms=50)

        assert bridge_result.analyzability_score == 95.0

    def test_policy_name_extracted_from_metadata(self):
        mock_result = self._make_mock_result()

        bridge_result = _map_scan_result(mock_result, elapsed_ms=50)

        assert bridge_result.policy_name == "strict"
        assert bridge_result.policy_fingerprint == "abc123"


class TestFixGeminiUnionTypes:
    """Tests for the Gemini schema union-type converter."""

    def test_string_null_union_becomes_nullable_string(self):
        schema = {"type": ["string", "null"], "description": "Optional field"}
        result = _fix_gemini_union_types(schema)
        assert result == {"type": "STRING", "nullable": True, "description": "Optional field"}

    def test_plain_string_uppercased(self):
        schema = {"type": "string", "description": "Required field"}
        result = _fix_gemini_union_types(schema)
        assert result == {"type": "STRING", "description": "Required field"}

    def test_additional_properties_stripped(self):
        schema = {"type": "object", "additionalProperties": False, "properties": {}}
        result = _fix_gemini_union_types(schema)
        assert "additionalProperties" not in result
        assert result["type"] == "OBJECT"

    def test_nested_properties_converted(self):
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "location": {"type": ["string", "null"]},
            },
        }
        result = _fix_gemini_union_types(schema)
        assert result["properties"]["name"] == {"type": "STRING"}
        assert result["properties"]["location"] == {"type": "STRING", "nullable": True}

    def test_array_items_converted(self):
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence": {"type": ["string", "null"]},
                },
            },
        }
        result = _fix_gemini_union_types(schema)
        assert result["items"]["properties"]["evidence"] == {"type": "STRING", "nullable": True}

    def test_passthrough_for_non_dict(self):
        assert _fix_gemini_union_types(42) == 42
        assert _fix_gemini_union_types("hello") == "hello"
        assert _fix_gemini_union_types(None) is None

    def test_list_of_schemas_converted(self):
        schemas = [{"type": "string"}, {"type": ["string", "null"]}]
        result = _fix_gemini_union_types(schemas)
        assert result == [{"type": "STRING"}, {"type": "STRING", "nullable": True}]

    def test_all_json_types_uppercased(self):
        for lower, upper in [
            ("string", "STRING"),
            ("number", "NUMBER"),
            ("integer", "INTEGER"),
            ("boolean", "BOOLEAN"),
            ("array", "ARRAY"),
            ("object", "OBJECT"),
            ("null", "NULL"),
        ]:
            assert _fix_gemini_union_types({"type": lower}) == {"type": upper}

    def test_real_scanner_schema(self):
        """Verify against the actual fields that cause the Gemini failure."""
        schema = {
            "type": "object",
            "properties": {
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "severity": {"type": "string", "enum": ["CRITICAL", "HIGH"]},
                            "aisubtech": {"type": ["string", "null"]},
                            "title": {"type": "string"},
                            "location": {"type": ["string", "null"]},
                            "evidence": {"type": ["string", "null"]},
                            "remediation": {"type": ["string", "null"]},
                        },
                        "required": ["severity", "title"],
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        }
        result = _fix_gemini_union_types(schema)

        items_props = result["properties"]["findings"]["items"]["properties"]
        assert items_props["aisubtech"] == {"type": "STRING", "nullable": True}
        assert items_props["location"] == {"type": "STRING", "nullable": True}
        assert items_props["evidence"] == {"type": "STRING", "nullable": True}
        assert items_props["remediation"] == {"type": "STRING", "nullable": True}
        assert items_props["severity"] == {"type": "STRING", "enum": ["CRITICAL", "HIGH"]}
        assert items_props["title"] == {"type": "STRING"}

        assert "additionalProperties" not in result
        assert "additionalProperties" not in result["properties"]["findings"]["items"]
