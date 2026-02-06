"""Tests for decision_hub.domain.orgs -- organisation validation logic."""

import pytest

from decision_hub.domain.orgs import validate_org_slug, validate_role


# ---------------------------------------------------------------------------
# validate_org_slug
# ---------------------------------------------------------------------------

class TestValidateOrgSlug:
    """Slug validation: lowercase alphanumeric + hyphens, 1-64 chars."""

    @pytest.mark.parametrize(
        "slug",
        [
            "a",                    # single char
            "my-org",               # typical slug
            "org123",               # numbers allowed
            "a" * 64,               # max length
            "abc-def-ghi",          # multiple hyphens
            "0-start-with-digit",   # digits at start
        ],
    )
    def test_valid_slugs(self, slug: str) -> None:
        assert validate_org_slug(slug) == slug

    @pytest.mark.parametrize(
        "slug,reason",
        [
            ("", "empty string"),
            ("a" * 65, "too long (65 chars)"),
            ("-starts-with-hyphen", "leading hyphen"),
            ("ends-with-hyphen-", "trailing hyphen"),
            ("UpperCase", "uppercase letters"),
            ("has space", "contains space"),
            ("special!chars", "special characters"),
            ("under_score", "underscore not allowed"),
        ],
    )
    def test_invalid_slugs(self, slug: str, reason: str) -> None:
        with pytest.raises(ValueError):
            validate_org_slug(slug)


# ---------------------------------------------------------------------------
# validate_role
# ---------------------------------------------------------------------------

class TestValidateRole:

    @pytest.mark.parametrize("role", ["owner", "admin", "member"])
    def test_valid_roles(self, role: str) -> None:
        assert validate_role(role) == role

    @pytest.mark.parametrize(
        "role",
        ["superadmin", "viewer", "", "Owner", "ADMIN"],
    )
    def test_invalid_roles(self, role: str) -> None:
        with pytest.raises(ValueError):
            validate_role(role)
