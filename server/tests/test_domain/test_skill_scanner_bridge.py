"""Tests for domain/skill_scanner_bridge.py — the adapter between skill-scanner and dhub."""

import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest

import decision_hub.domain.skill_scanner_bridge as bridge_mod
from decision_hub.domain.skill_scanner_bridge import (
    BridgeScanResult,
    _check_llm_degradation,
    _effective_max_severity,
    _error_scan_result,
    _find_skill_root,
    _fix_gemini_union_types,
    _map_scan_result,
    _patch_gemini_schema_sanitizer,
    _run_meta_analysis,
    _safe_extract_zip,
    scan_skill_dir,
    scan_skill_zip,
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

    def test_unknown_defaults_to_f(self):
        assert severity_to_grade("UNKNOWN") == "F"


class TestEffectiveMaxSeverity:
    def test_no_meta_returns_raw(self):
        findings = [{"severity": "MEDIUM", "metadata": {}}]
        assert _effective_max_severity(findings, "MEDIUM") == "MEDIUM"

    def test_all_fps_returns_safe(self):
        findings = [
            {"severity": "MEDIUM", "metadata": {"meta_false_positive": True}},
            {"severity": "HIGH", "metadata": {"meta_false_positive": True}},
        ]
        assert _effective_max_severity(findings, "HIGH") == "SAFE"

    def test_fp_filtered_lowers_severity(self):
        findings = [
            {"severity": "MEDIUM", "metadata": {"meta_false_positive": True}},
            {"severity": "LOW", "metadata": {"meta_false_positive": False}},
            {"severity": "INFO", "metadata": {"meta_false_positive": False}},
        ]
        assert _effective_max_severity(findings, "MEDIUM") == "LOW"

    def test_no_findings_returns_raw(self):
        assert _effective_max_severity([], "SAFE") == "SAFE"

    def test_mixed_with_critical_non_fp(self):
        findings = [
            {"severity": "MEDIUM", "metadata": {"meta_false_positive": True}},
            {"severity": "CRITICAL", "metadata": {"meta_false_positive": False}},
        ]
        assert _effective_max_severity(findings, "CRITICAL") == "CRITICAL"


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

    def test_meta_analysis_override_takes_precedence(self):
        mock_result = self._make_mock_result()
        override = {"risk_level": "SAFE", "summary": "All clear"}

        bridge_result = _map_scan_result(mock_result, elapsed_ms=50, meta_analysis_override=override)

        assert bridge_result.meta_analysis == override

    def test_meta_analysis_none_without_override(self):
        mock_result = self._make_mock_result()

        bridge_result = _map_scan_result(mock_result, elapsed_ms=50)

        assert bridge_result.meta_analysis is None

    def test_fp_findings_excluded_from_grade(self):
        """Grade should reflect non-FP findings only when meta-analysis is present."""
        medium_fp = MagicMock()
        medium_fp.rule_id = "FP-001"
        medium_fp.category = "prompt_injection"
        sev_m = MagicMock()
        sev_m.name = "MEDIUM"
        medium_fp.severity = sev_m
        medium_fp.title = "False positive"
        medium_fp.description = None
        medium_fp.file_path = None
        medium_fp.line_number = None
        medium_fp.snippet = None
        medium_fp.remediation = None
        medium_fp.analyzer = "llm_analyzer"
        medium_fp.to_dict.return_value = {
            "metadata": {"meta_false_positive": True, "meta_reason": "benign"},
        }

        low_valid = MagicMock()
        low_valid.rule_id = "V-001"
        low_valid.category = "policy_violation"
        sev_l = MagicMock()
        sev_l.name = "LOW"
        low_valid.severity = sev_l
        low_valid.title = "Valid finding"
        low_valid.description = None
        low_valid.file_path = None
        low_valid.line_number = None
        low_valid.snippet = None
        low_valid.remediation = None
        low_valid.analyzer = "static"
        low_valid.to_dict.return_value = {
            "metadata": {"meta_false_positive": False},
        }

        mock_result = self._make_mock_result(
            is_safe=True,
            max_severity_name="MEDIUM",
            findings=[medium_fp, low_valid],
        )

        bridge_result = _map_scan_result(mock_result, elapsed_ms=100)

        assert bridge_result.grade == "A"
        assert bridge_result.findings_count == 2


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


class TestRunMetaAnalysis:
    """Tests for the MetaAnalyzer post-processing step."""

    def _make_scan_result(self, *, findings=None, analyzers_used=None):
        result = MagicMock()
        result.findings = findings or []
        result.analyzers_used = analyzers_used or ["static_analyzer"]
        return result

    def _make_settings(self, *, api_key="fake-key", model="gemini-2.0-flash"):
        settings = MagicMock()
        settings.google_api_key = api_key
        settings.gemini_model = model
        return settings

    def test_skips_when_no_api_key(self, tmp_path):
        result = self._make_scan_result(findings=[MagicMock()])
        settings = self._make_settings(api_key="")

        meta_dict, _findings, error = _run_meta_analysis(result, tmp_path, settings)

        assert meta_dict is None
        assert error is None

    def test_skips_when_no_findings(self, tmp_path):
        result = self._make_scan_result(findings=[])
        settings = self._make_settings()

        meta_dict, findings, error = _run_meta_analysis(result, tmp_path, settings)

        assert meta_dict is None
        assert findings == []
        assert error is None

    @patch("decision_hub.domain.skill_scanner_bridge.asyncio")
    @patch("decision_hub.domain.skill_scanner_bridge._capture_stdout_during")
    def test_returns_meta_dict_on_success(self, mock_capture, mock_asyncio, tmp_path):
        finding = MagicMock()
        result = self._make_scan_result(findings=[finding])
        settings = self._make_settings()

        mock_meta_result = MagicMock()
        mock_meta_result.validated_findings = [{"rule_id": "X"}]
        mock_meta_result.false_positives = []
        mock_meta_result.missed_threats = []
        mock_meta_result.to_dict.return_value = {"overall_risk_assessment": {"risk_level": "SAFE"}}

        mock_capture.return_value = (mock_meta_result, "")

        enriched_findings = [MagicMock()]

        with (
            patch("skill_scanner.core.analyzers.MetaAnalyzer") as MockMeta,
            patch(
                "skill_scanner.core.analyzers.meta_analyzer.apply_meta_analysis_to_results",
                return_value=enriched_findings,
            ),
            patch("skill_scanner.core.loader.SkillLoader") as MockLoader,
        ):
            MockMeta.return_value = MagicMock()
            MockLoader.return_value.load_skill.return_value = MagicMock()

            meta_dict, _findings, error = _run_meta_analysis(result, tmp_path, settings)

        assert meta_dict == {"overall_risk_assessment": {"risk_level": "SAFE"}}
        assert error is None

    def test_returns_none_on_import_error(self, tmp_path):
        finding = MagicMock()
        result = self._make_scan_result(findings=[finding])
        settings = self._make_settings()

        with patch.dict("sys.modules", {"skill_scanner.core.analyzers": None}):
            meta_dict, _findings, error = _run_meta_analysis(result, tmp_path, settings)

        assert meta_dict is None
        assert error is None

    @patch("decision_hub.domain.skill_scanner_bridge.asyncio")
    @patch("decision_hub.domain.skill_scanner_bridge._capture_stdout_during")
    def test_returns_error_on_runtime_failure(self, mock_capture, mock_asyncio, tmp_path):
        finding = MagicMock()
        result = self._make_scan_result(findings=[finding])
        settings = self._make_settings()

        mock_capture.side_effect = RuntimeError("LLM API timeout")

        with (
            patch("skill_scanner.core.analyzers.MetaAnalyzer"),
            patch("skill_scanner.core.analyzers.meta_analyzer.apply_meta_analysis_to_results"),
            patch("skill_scanner.core.loader.SkillLoader"),
        ):
            meta_dict, _findings, error = _run_meta_analysis(result, tmp_path, settings)

        assert meta_dict is None
        assert isinstance(error, RuntimeError)
        assert "LLM API timeout" in str(error)

    @patch("decision_hub.domain.skill_scanner_bridge.asyncio")
    @patch("decision_hub.domain.skill_scanner_bridge._capture_stdout_during")
    def test_uses_gemini_prefix_for_litellm(self, mock_capture, mock_asyncio, tmp_path):
        finding = MagicMock()
        result = self._make_scan_result(findings=[finding])
        settings = self._make_settings(model="gemini-2.0-flash")

        mock_capture.return_value = (MagicMock(), "")

        with (
            patch("skill_scanner.core.analyzers.MetaAnalyzer") as MockMeta,
            patch("skill_scanner.core.analyzers.meta_analyzer.apply_meta_analysis_to_results", return_value=[]),
            patch("skill_scanner.core.loader.SkillLoader"),
        ):
            MockMeta.return_value = MagicMock()
            _run_meta_analysis(result, tmp_path, settings)
            MockMeta.assert_called_once_with(model="gemini/gemini-2.0-flash", api_key="fake-key")


class TestCheckLlmDegradation:
    """Tests for silent LLM failure detection (stdout-based)."""

    def _make_result(
        self,
        *,
        findings: list[dict] | None = None,
    ) -> BridgeScanResult:
        findings = findings or []
        return BridgeScanResult(
            is_safe=True,
            max_severity="SAFE",
            grade="A",
            findings_count=len(findings),
            findings=findings,
            analyzers_used=["static_analyzer", "llm_analyzer", "meta_analyzer"],
            analyzability_score=90.0,
            scan_duration_ms=500,
            policy_name="balanced",
            policy_fingerprint="abc",
            full_report={},
            meta_analysis=None,
        )

    def test_no_degradation_when_llm_not_expected(self):
        result = self._make_result()
        checked = _check_llm_degradation(result, llm_expected=False, captured_stdout="Error in LLM")
        assert checked is result

    def test_no_degradation_when_stdout_empty(self):
        result = self._make_result()
        checked = _check_llm_degradation(result, llm_expected=True, captured_stdout="")
        assert checked is result

    def test_no_degradation_when_stdout_clean(self):
        result = self._make_result()
        checked = _check_llm_degradation(result, llm_expected=True, captured_stdout="Processing skill...")
        assert checked is result

    def test_degradation_detected_on_error_stdout(self):
        result = self._make_result()
        checked = _check_llm_degradation(result, llm_expected=True, captured_stdout="Error calling Gemini API")
        assert checked is not result
        assert checked.findings_count == 1
        degradation = checked.findings[0]
        assert degradation["rule_id"] == "LLM_DEGRADED"
        assert degradation["severity"] == "INFO"
        assert degradation["analyzer"] == "bridge"

    def test_degradation_on_exception_stdout(self):
        result = self._make_result()
        checked = _check_llm_degradation(
            result,
            llm_expected=True,
            captured_stdout="Exception: ConnectionError",
        )
        assert checked is not result
        assert checked.findings[0]["rule_id"] == "LLM_DEGRADED"

    def test_degradation_on_traceback_stdout(self):
        result = self._make_result()
        checked = _check_llm_degradation(
            result,
            llm_expected=True,
            captured_stdout="Traceback (most recent call last):\n  File ...",
        )
        assert checked is not result

    def test_degradation_preserves_existing_findings(self):
        static_finding = {"analyzer": "static", "rule_id": "SS-001", "severity": "LOW"}
        result = self._make_result(findings=[static_finding])
        checked = _check_llm_degradation(result, llm_expected=True, captured_stdout="Error: LLM failed")
        assert checked.findings_count == 2
        assert checked.findings[0] == static_finding
        assert checked.findings[1]["rule_id"] == "LLM_DEGRADED"

    def test_degradation_does_not_change_grade(self):
        result = self._make_result()
        checked = _check_llm_degradation(result, llm_expected=True, captured_stdout="failed to connect")
        assert checked.grade == result.grade

    def test_degradation_preserves_all_other_fields(self):
        result = self._make_result()
        checked = _check_llm_degradation(result, llm_expected=True, captured_stdout="error in LLM call")
        assert checked.is_safe == result.is_safe
        assert checked.max_severity == result.max_severity
        assert checked.analyzers_used == result.analyzers_used
        assert checked.analyzability_score == result.analyzability_score
        assert checked.scan_duration_ms == result.scan_duration_ms
        assert checked.policy_name == result.policy_name
        assert checked.policy_fingerprint == result.policy_fingerprint
        assert checked.full_report == result.full_report
        assert checked.meta_analysis == result.meta_analysis


class TestPatchGeminiSchemaSanitizer:
    """Tests for _patch_gemini_schema_sanitizer edge cases."""

    def setup_method(self):
        # Reset global _PATCHED before each test
        bridge_mod._PATCHED = False

    def teardown_method(self):
        bridge_mod._PATCHED = False

    def test_sets_patched_on_import_error(self):
        with patch.dict("sys.modules", {"skill_scanner.core.analyzers.llm_request_handler": None}):
            _patch_gemini_schema_sanitizer()
        assert bridge_mod._PATCHED is True

    def test_sets_patched_when_hasattr_fails(self):
        mock_handler = MagicMock(spec=[])  # no attributes
        mock_module = MagicMock()
        mock_module.LLMRequestHandler = mock_handler
        with patch.dict("sys.modules", {"skill_scanner.core.analyzers.llm_request_handler": mock_module}):
            _patch_gemini_schema_sanitizer()
        assert bridge_mod._PATCHED is True

    def test_idempotent_after_first_call(self):
        bridge_mod._PATCHED = True
        # Should return immediately without doing anything
        _patch_gemini_schema_sanitizer()
        assert bridge_mod._PATCHED is True


class TestScanExceptionPropagation:
    """Tests that critical exceptions propagate from scan_skill_dir/scan_skill_zip."""

    def _make_settings(self):
        settings = MagicMock()
        settings.google_api_key = ""
        return settings

    @patch("decision_hub.domain.skill_scanner_bridge._build_scanner")
    def test_scan_skill_dir_propagates_import_error(self, mock_build, tmp_path):
        mock_build.side_effect = ImportError("no scanner")
        with pytest.raises(ImportError, match="no scanner"):
            scan_skill_dir(tmp_path, self._make_settings())

    @patch("decision_hub.domain.skill_scanner_bridge._build_scanner")
    def test_scan_skill_dir_propagates_memory_error(self, mock_build, tmp_path):
        mock_build.side_effect = MemoryError()
        with pytest.raises(MemoryError):
            scan_skill_dir(tmp_path, self._make_settings())

    def test_scan_skill_zip_propagates_bad_zip_file(self):
        with pytest.raises(zipfile.BadZipFile):
            scan_skill_zip(b"not a zip", self._make_settings())

    def test_scan_skill_zip_propagates_value_error(self):
        """Path traversal in zip should raise ValueError."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../../../etc/passwd", "malicious")
        with pytest.raises(ValueError, match="would escape"):
            scan_skill_zip(buf.getvalue(), self._make_settings())

    @patch("decision_hub.domain.skill_scanner_bridge._build_scanner")
    @patch("decision_hub.domain.skill_scanner_bridge._safe_extract_zip")
    def test_scan_skill_zip_propagates_import_error(self, mock_extract, mock_build, tmp_path):
        mock_build.side_effect = ImportError("no scanner")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", "---\nname: test\n---\n")
        with pytest.raises(ImportError, match="no scanner"):
            scan_skill_zip(buf.getvalue(), self._make_settings())
