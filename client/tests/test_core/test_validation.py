"""Tests for dhub.core.validation -- version bumping (client-specific).

Semver and skill name validation tests live in shared/tests/test_validation.py
since validate_semver and validate_skill_name are defined in dhub_core.
"""

import pytest

from dhub.core.validation import bump_version


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
