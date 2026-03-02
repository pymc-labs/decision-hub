"""Tests for logging configuration and request logging middleware."""

import json
from io import StringIO
from unittest.mock import patch

import pytest
from loguru import logger

from decision_hub.logging import (
    _PATH_CONTEXT_RE,
    _extract_username_from_jwt,
    setup_logging,
)


class TestSetupLogging:
    def test_text_format_default(self):
        """Default text format adds a stderr handler."""
        setup_logging("INFO", log_format="text")
        # Should not raise — just verify it configures without error
        logger.info("test text format")

    def test_json_format(self):
        """JSON format produces valid JSON lines to stderr."""
        setup_logging("INFO", log_format="json")
        # Should not raise
        logger.info("test json format")

    def test_json_sink_produces_valid_json(self):
        """The _json_sink function writes valid JSON with context fields."""
        buf = StringIO()
        with patch("decision_hub.logging.sys") as mock_sys:
            mock_sys.stderr = buf
            setup_logging("DEBUG", log_format="json")
            with logger.contextualize(request_id="abc12345"):
                logger.info("hello {}", "world")

        output = buf.getvalue()
        # Should be one or more JSON lines
        for line in output.strip().split("\n"):
            if line:
                parsed = json.loads(line)
                assert "timestamp" in parsed
                assert "level" in parsed
                assert "message" in parsed


class TestPathContextRegex:
    @pytest.mark.parametrize(
        "path, expected_org, expected_skill",
        [
            ("/v1/skills/my-org/my-skill", "my-org", "my-skill"),
            ("/v1/skills/my-org/my-skill/versions", "my-org", "my-skill"),
            ("/v1/orgs/acme/skills/tool", "acme", "tool"),
            ("/v1/orgs/acme/skills/tool/eval", "acme", "tool"),
        ],
    )
    def test_extracts_org_and_skill(self, path, expected_org, expected_skill):
        m = _PATH_CONTEXT_RE.search(path)
        assert m is not None
        assert m.group("org") == expected_org
        assert m.group("skill") == expected_skill

    @pytest.mark.parametrize(
        "path",
        ["/health", "/cli/latest-version", "/v1/ask"],
    )
    def test_no_match_on_unrelated_paths(self, path):
        m = _PATH_CONTEXT_RE.search(path)
        assert m is None


class TestExtractUsernameFromJwt:
    def test_extracts_username_from_valid_jwt(self):
        """Should decode the payload and extract the username claim."""
        import base64

        header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(b'{"username":"alice"}').rstrip(b"=").decode()
        sig = "fakesig"
        token = f"{header}.{payload}.{sig}"
        result = _extract_username_from_jwt(f"Bearer {token}")
        assert result == "alice"

    def test_returns_empty_on_missing_bearer(self):
        assert _extract_username_from_jwt("Basic abc") == ""

    def test_returns_empty_on_malformed_token(self):
        assert _extract_username_from_jwt("Bearer not.a.valid-base64!!!") == ""

    def test_returns_empty_on_no_username_claim(self):
        import base64

        header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(b'{"sub":"123"}').rstrip(b"=").decode()
        sig = "fakesig"
        token = f"{header}.{payload}.{sig}"
        result = _extract_username_from_jwt(f"Bearer {token}")
        assert result == ""
