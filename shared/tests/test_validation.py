"""Tests for dhub_core.validation — shared validation functions."""

import pytest

from dhub_core.validation import FIRST_VERSION, validate_semver, validate_skill_name


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


def test_first_version_is_valid() -> None:
    """FIRST_VERSION should itself be valid semver."""
    assert validate_semver(FIRST_VERSION) == FIRST_VERSION
