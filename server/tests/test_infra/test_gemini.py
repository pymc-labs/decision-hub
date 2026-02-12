"""Tests for decision_hub.infra.gemini -- schema validation of LLM safety responses."""

from decision_hub.infra.gemini import (
    CodeSafetyJudgment,
    PromptSafetyJudgment,
)


class TestCodeSafetyJudgmentValidation:
    """Tests for CodeSafetyJudgment Pydantic model."""

    def test_valid_judgment(self):
        j = CodeSafetyJudgment(
            file="main.py",
            label="subprocess invocation",
            dangerous=False,
            reason="legitimate build tool",
        )
        assert j.file == "main.py"
        assert j.dangerous is False

    def test_missing_field_raises(self):
        """Missing required fields should raise ValidationError."""
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CodeSafetyJudgment(
                file="main.py",
                label="test",
                # missing 'dangerous' and 'reason'
            )

    def test_extra_fields_ignored(self):
        """Extra fields from LLM are silently ignored."""
        j = CodeSafetyJudgment(
            file="main.py",
            label="test",
            dangerous=True,
            reason="bad",
            extra_field="ignored",
        )
        assert j.dangerous is True

    def test_model_dump_roundtrip(self):
        j = CodeSafetyJudgment(
            file="main.py",
            label="subprocess invocation",
            dangerous=True,
            reason="shell injection",
        )
        d = j.model_dump()
        assert d == {
            "file": "main.py",
            "label": "subprocess invocation",
            "dangerous": True,
            "reason": "shell injection",
        }


class TestPromptSafetyJudgmentValidation:
    """Tests for PromptSafetyJudgment Pydantic model."""

    def test_valid_judgment(self):
        j = PromptSafetyJudgment(
            label="instruction override",
            dangerous=False,
            ambiguous=True,
            reason="unclear intent",
        )
        assert j.ambiguous is True
        assert j.dangerous is False

    def test_missing_field_raises(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PromptSafetyJudgment(
                label="test",
                # missing dangerous, ambiguous, reason
            )

    def test_model_dump_roundtrip(self):
        j = PromptSafetyJudgment(
            label="exfiltration URL",
            dangerous=True,
            ambiguous=False,
            reason="sends data to attacker",
        )
        d = j.model_dump()
        assert d == {
            "label": "exfiltration URL",
            "dangerous": True,
            "ambiguous": False,
            "reason": "sends data to attacker",
        }
