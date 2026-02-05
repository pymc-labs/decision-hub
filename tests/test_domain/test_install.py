"""Tests for decision_hub.domain.install -- checksum verification and path helpers."""

import hashlib
from pathlib import Path

import pytest

from decision_hub.domain.install import get_dhub_skill_path, verify_checksum


class TestVerifyChecksum:

    def test_valid_checksum(self) -> None:
        """Matching checksum should not raise."""
        data = b"hello world"
        expected = hashlib.sha256(data).hexdigest()
        # Should complete without error
        verify_checksum(data, expected)

    def test_invalid_checksum(self) -> None:
        """Mismatching checksum should raise ValueError."""
        data = b"hello world"
        wrong_checksum = "0" * 64

        with pytest.raises(ValueError, match="Checksum mismatch"):
            verify_checksum(data, wrong_checksum)

    def test_empty_data(self) -> None:
        """Checksum of empty bytes should be the SHA-256 of nothing."""
        data = b""
        expected = hashlib.sha256(data).hexdigest()
        verify_checksum(data, expected)


class TestGetDhubSkillPath:

    def test_path_structure(self) -> None:
        """The path should be ~/.dhub/skills/{org}/{skill}."""
        path = get_dhub_skill_path("my-org", "my-skill")

        assert path == Path.home() / ".dhub" / "skills" / "my-org" / "my-skill"

    def test_returns_path_object(self) -> None:
        """Should return a Path, not a string."""
        path = get_dhub_skill_path("org", "skill")
        assert isinstance(path, Path)

    def test_different_orgs_produce_different_paths(self) -> None:
        """Two different orgs should give different skill paths."""
        path_a = get_dhub_skill_path("org-a", "skill")
        path_b = get_dhub_skill_path("org-b", "skill")
        assert path_a != path_b
