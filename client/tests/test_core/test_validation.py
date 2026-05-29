"""Tests for dhub.core.validation -- version bumping (client-specific).

Semver and skill name validation tests live in shared/tests/test_validation.py
since validate_semver and validate_skill_name are defined in dhub_core.
"""

import pytest

from dhub.core.validation import bump_version, parse_semver, parse_skill_ref


class TestBumpVersion:
    @pytest.mark.parametrize(
        "current,bump,expected",
        [
            ("1.2.3", "patch", "1.2.4"),
            ("1.2.3", "minor", "1.3.0"),
            ("1.2.3", "major", "2.0.0"),
            ("0.1.0", "patch", "0.1.1"),
            ("0.0.0", "patch", "0.0.1"),
            ("0.0.0", "minor", "0.1.0"),
            ("0.0.0", "major", "1.0.0"),
            ("9.9.9", "patch", "9.9.10"),
            ("0.1.0", "minor", "0.2.0"),
            ("0.1.0", "major", "1.0.0"),
        ],
    )
    def test_bump_version(self, current: str, bump: str, expected: str) -> None:
        assert bump_version(current, bump) == expected

    def test_bump_version_default_is_patch(self) -> None:
        assert bump_version("1.0.0") == "1.0.1"

    def test_bump_version_invalid_semver(self) -> None:
        with pytest.raises(ValueError):
            bump_version("not-a-version", "patch")

    def test_bump_version_unknown_level(self) -> None:
        with pytest.raises(ValueError, match="Unknown bump level"):
            bump_version("1.0.0", "micro")


class TestParseSemverReexport:
    """Verify parse_semver is accessible via the dhub.core.validation re-export.

    Full semver logic tests live in shared/tests/test_validation.py.
    This class only guards the re-export wiring.
    """

    def test_basic(self) -> None:
        assert parse_semver("1.2.3") == (1, 2, 3)

    def test_comparison(self) -> None:
        assert parse_semver("1.0.0") > parse_semver("0.9.0")

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_semver("not-a-version")


class TestParseSkillRef:
    """parse_skill_ref splits 'org/skill' and rejects malformed refs."""

    def test_valid(self) -> None:
        assert parse_skill_ref("pymc-labs/pymc-modeling") == ("pymc-labs", "pymc-modeling")

    def test_skill_name_may_not_be_empty(self) -> None:
        # "org/" splits into ["org", ""] -- length 2 but an empty skill name,
        # which would otherwise resolve to the org directory itself.
        with pytest.raises(ValueError, match="org/skill format"):
            parse_skill_ref("org/")

    def test_org_may_not_be_empty(self) -> None:
        with pytest.raises(ValueError, match="org/skill format"):
            parse_skill_ref("/skill")

    def test_lone_slash_rejected(self) -> None:
        with pytest.raises(ValueError, match="org/skill format"):
            parse_skill_ref("/")

    def test_missing_slash_rejected(self) -> None:
        with pytest.raises(ValueError, match="org/skill format"):
            parse_skill_ref("just-a-name")
