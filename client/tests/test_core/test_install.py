"""Tests for dhub.core.install -- checksum verification, path helpers, and uninstall."""

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest

from dhub.core.install import get_dhub_skill_path, uninstall_skill, verify_checksum


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


class TestUninstallSkill:
    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.core.install.list_linked_agents", return_value=["claude", "cursor"])
    @patch("dhub.core.install.unlink_skill_from_agent")
    def test_uninstall_removes_dir_and_symlinks(self, mock_unlink, mock_linked, mock_path, tmp_path: Path) -> None:
        """uninstall_skill removes the skill dir and all agent symlinks."""
        skill_dir = tmp_path / "org" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("content")
        mock_path.return_value = skill_dir

        result = uninstall_skill("org", "my-skill")

        assert result == ["claude", "cursor"]
        assert not skill_dir.exists()
        assert mock_unlink.call_count == 2

    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.core.install.list_linked_agents", return_value=[])
    def test_uninstall_no_symlinks(self, mock_linked, mock_path, tmp_path: Path) -> None:
        """uninstall_skill works when no agents are linked."""
        skill_dir = tmp_path / "org" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("content")
        mock_path.return_value = skill_dir

        result = uninstall_skill("org", "my-skill")

        assert result == []
        assert not skill_dir.exists()

    @patch("dhub.core.install.get_dhub_skill_path")
    def test_uninstall_not_installed_raises(self, mock_path, tmp_path: Path) -> None:
        """uninstall_skill raises FileNotFoundError for missing skills."""
        mock_path.return_value = tmp_path / "org" / "nonexistent"

        with pytest.raises(FileNotFoundError, match="not installed"):
            uninstall_skill("org", "nonexistent")

    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.core.install.list_linked_agents", return_value=[])
    def test_uninstall_cleans_empty_org_dir(self, mock_linked, mock_path, tmp_path: Path) -> None:
        """uninstall_skill removes the empty org directory after cleanup."""
        org_dir = tmp_path / "org"
        skill_dir = org_dir / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("content")
        mock_path.return_value = skill_dir

        uninstall_skill("org", "my-skill")

        assert not org_dir.exists()

    @patch("dhub.core.install.get_dhub_skill_path")
    @patch("dhub.core.install.list_linked_agents", return_value=[])
    def test_uninstall_keeps_org_dir_with_other_skills(self, mock_linked, mock_path, tmp_path: Path) -> None:
        """uninstall_skill keeps the org dir if other skills remain."""
        org_dir = tmp_path / "org"
        skill_dir = org_dir / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("content")
        # Another skill in same org
        other_skill = org_dir / "other-skill"
        other_skill.mkdir()
        mock_path.return_value = skill_dir

        uninstall_skill("org", "my-skill")

        assert not skill_dir.exists()
        assert org_dir.exists()
