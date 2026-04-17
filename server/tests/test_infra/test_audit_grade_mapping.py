"""Tests for audit log grade ↔ DB mapping (VARCHAR(1) constraint)."""

from decision_hub.infra.database import _AUDIT_GRADE_FROM_DB, _AUDIT_GRADE_TO_DB


class TestAuditGradeMapping:
    def test_pending_maps_to_single_char(self):
        assert _AUDIT_GRADE_TO_DB["pending"] == "P"
        assert len(_AUDIT_GRADE_TO_DB["pending"]) == 1

    def test_roundtrip_pending(self):
        db_val = _AUDIT_GRADE_TO_DB.get("pending", "pending")
        app_val = _AUDIT_GRADE_FROM_DB.get(db_val, db_val)
        assert app_val == "pending"

    def test_standard_grades_pass_through(self):
        for grade in ("A", "B", "C", "F"):
            assert _AUDIT_GRADE_TO_DB.get(grade, grade) == grade
            assert _AUDIT_GRADE_FROM_DB.get(grade, grade) == grade
