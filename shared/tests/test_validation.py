"""Tests for dhub_core.validation — shared validation functions."""

import pytest

from dhub_core.validation import (
    FIRST_VERSION,
    bump_version,
    parse_semver,
    validate_org_slug,
    validate_semver,
    validate_skill_name,
    validate_slug,
)


class TestValidateSemver:
    """validate_semver accepts valid semver and rejects invalid."""

    @pytest.mark.parametrize("version", ["0.0.0", "0.0.1", "0.1.0", "1.0.0", "12.34.56", "999.999.999"])
    def test_valid(self, version: str) -> None:
        assert validate_semver(version) == version

    @pytest.mark.parametrize(
        "version",
        [
            "",
            "1.0",
            "1.0.0.0",
            "v1.0.0",
            "01.0.0",
            "0.01.0",
            "0.0.01",
            "1.0.0-beta",
            "abc",
        ],
    )
    def test_invalid(self, version: str) -> None:
        with pytest.raises(ValueError, match="Invalid semver"):
            validate_semver(version)


class TestParseSemver:
    """parse_semver parses valid versions into tuples."""

    def test_standard(self) -> None:
        assert parse_semver("1.2.3") == (1, 2, 3)

    def test_zeros(self) -> None:
        assert parse_semver("0.0.0") == (0, 0, 0)

    def test_comparison(self) -> None:
        assert parse_semver("2.0.0") > parse_semver("1.9.9")
        assert parse_semver("1.0.0") < parse_semver("2.0.0")

    @pytest.mark.parametrize("version", ["1.0", "1", "1.0.0.0", "abc", ""])
    def test_invalid_raises_value_error(self, version: str) -> None:
        with pytest.raises(ValueError, match="Invalid semver"):
            parse_semver(version)


class TestBumpVersion:
    """bump_version increments correct component."""

    @pytest.mark.parametrize(
        "current,bump,expected",
        [
            ("1.2.3", "patch", "1.2.4"),
            ("1.2.3", "minor", "1.3.0"),
            ("1.2.3", "major", "2.0.0"),
            ("0.0.0", "patch", "0.0.1"),
            ("0.0.0", "minor", "0.1.0"),
            ("0.0.0", "major", "1.0.0"),
        ],
    )
    def test_bump(self, current: str, bump: str, expected: str) -> None:
        assert bump_version(current, bump) == expected

    def test_default_is_patch(self) -> None:
        assert bump_version("1.0.0") == "1.0.1"

    def test_invalid_semver(self) -> None:
        with pytest.raises(ValueError):
            bump_version("not-a-version", "patch")

    def test_unknown_level(self) -> None:
        with pytest.raises(ValueError, match="Unknown bump level"):
            bump_version("1.0.0", "micro")


class TestValidateSkillName:
    """validate_skill_name accepts valid names and rejects invalid."""

    @pytest.mark.parametrize("name", ["a", "my-skill", "a1", "skill123", "abc-def-ghi", "a" * 64])
    def test_valid(self, name: str) -> None:
        assert validate_skill_name(name) == name

    @pytest.mark.parametrize(
        "name",
        ["", "-leading", "trailing-", "UPPER", "has space", "under_score", "a" * 65],
    )
    def test_invalid(self, name: str) -> None:
        with pytest.raises(ValueError, match="Invalid skill name"):
            validate_skill_name(name)


class TestValidateOrgSlug:
    """validate_org_slug uses the same pattern but reports 'org slug'."""

    @pytest.mark.parametrize("slug", ["a", "my-org", "a1", "abc-def-ghi"])
    def test_valid(self, slug: str) -> None:
        assert validate_org_slug(slug) == slug

    @pytest.mark.parametrize("slug", ["", "-leading", "trailing-", "UPPER", "has space", "a" * 65])
    def test_invalid(self, slug: str) -> None:
        with pytest.raises(ValueError, match="Invalid org slug"):
            validate_org_slug(slug)


class TestValidateSlug:
    """validate_slug is the generic version with a custom label."""

    def test_custom_label(self) -> None:
        with pytest.raises(ValueError, match="Invalid repo slug"):
            validate_slug("-bad", label="repo slug")


def test_first_version_is_valid() -> None:
    """FIRST_VERSION should itself be valid semver."""
    assert validate_semver(FIRST_VERSION) == FIRST_VERSION
