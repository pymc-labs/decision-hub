"""Unit tests for Settings properties."""

from typing import ClassVar

import pytest

from decision_hub.settings import Settings, create_settings


class TestBlockedOrgs:
    """Verify blocked_orgs property parses the comma-separated slug list."""

    def test_empty_string(self):
        s = Settings.model_construct(blocked_org_slugs="")
        assert s.blocked_orgs == frozenset()

    def test_single_org(self):
        s = Settings.model_construct(blocked_org_slugs="badorg")
        assert s.blocked_orgs == frozenset({"badorg"})

    def test_multiple_orgs(self):
        s = Settings.model_construct(blocked_org_slugs="openclaw,steipete")
        assert s.blocked_orgs == frozenset({"openclaw", "steipete"})

    def test_whitespace_trimmed(self):
        s = Settings.model_construct(blocked_org_slugs=" openclaw , steipete ")
        assert s.blocked_orgs == frozenset({"openclaw", "steipete"})

    def test_lowercase_normalized(self):
        s = Settings.model_construct(blocked_org_slugs="OpenClaw,STEIPETE")
        assert s.blocked_orgs == frozenset({"openclaw", "steipete"})

    def test_empty_segments_ignored(self):
        s = Settings.model_construct(blocked_org_slugs="openclaw,,steipete,")
        assert s.blocked_orgs == frozenset({"openclaw", "steipete"})


class TestJwtSecretValidation:
    """create_settings() must reject weak JWT secrets at startup.

    A short secret (<32 chars / 256 bits) is brute-forceable for HS256, so
    we fail fast rather than quietly issue forgeable tokens.
    """

    _REQUIRED: ClassVar[dict[str, str]] = {
        "DATABASE_URL": "postgresql://user:pw@localhost/db",
        "S3_BUCKET": "test-bucket",
        "AWS_ACCESS_KEY_ID": "x",
        "AWS_SECRET_ACCESS_KEY": "y",
        "GITHUB_CLIENT_ID": "id",
        "FERNET_KEY": "0" * 44,  # not validated; just present
    }

    def _set_env(self, monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
        for k, v in {**self._REQUIRED, **overrides}.items():
            monkeypatch.setenv(k, v)
        monkeypatch.setenv("DHUB_ENV", "nonexistent-env-for-test")

    def test_rejects_short_jwt_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set_env(monkeypatch, JWT_SECRET="too-short")
        with pytest.raises(RuntimeError, match="JWT_SECRET must be at least 32"):
            create_settings()

    def test_rejects_secret_at_31_chars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set_env(monkeypatch, JWT_SECRET="x" * 31)
        with pytest.raises(RuntimeError, match="32"):
            create_settings()

    def test_accepts_secret_at_32_chars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._set_env(monkeypatch, JWT_SECRET="x" * 32)
        settings = create_settings()
        assert settings.jwt_secret == "x" * 32

    def test_default_jwt_expiry_no_longer_one_year(self) -> None:
        """The historical 8760h (1 year) default has been shortened.

        Long-lived tokens with no refresh mechanism mean a leaked token has
        a year-long replay window. 720h (30d) is the new ceiling.
        """
        s = Settings.model_construct()
        assert s.jwt_expiry_hours == 720
