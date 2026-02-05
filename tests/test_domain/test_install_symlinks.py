"""Tests for symlink management in install module."""

from pathlib import Path
from unittest.mock import patch

import pytest

from decision_hub.domain import install


@pytest.fixture(autouse=True)
def _mock_agent_paths(tmp_path: Path) -> None:
    """Override AGENT_SKILL_PATHS to use temp directories for all tests."""
    mock_paths = {
        "claude": tmp_path / "agents" / "claude" / "skills",
        "cursor": tmp_path / "agents" / "cursor" / "skills",
        "opencode": tmp_path / "agents" / "opencode" / "skills",
        "gemini": tmp_path / "agents" / "gemini" / "skills",
    }
    with patch.object(install, "AGENT_SKILL_PATHS", mock_paths):
        yield


@pytest.fixture
def canonical_skill_dir(tmp_path: Path) -> Path:
    """Create and return a canonical skill directory under a mock .dhub path."""
    skill_dir = tmp_path / ".dhub" / "skills" / "myorg" / "myskill"
    skill_dir.mkdir(parents=True)
    # Add a SKILL.md so the directory has some content
    (skill_dir / "SKILL.md").write_text("# Skill content")
    return skill_dir


@pytest.fixture
def _mock_dhub_path(canonical_skill_dir: Path, tmp_path: Path) -> None:
    """Patch get_dhub_skill_path to return our temp canonical dir."""
    with patch.object(
        install,
        "get_dhub_skill_path",
        return_value=canonical_skill_dir,
    ):
        yield


class TestGetAgentSkillPaths:
    """Tests for get_agent_skill_paths."""

    def test_returns_dict_copy(self) -> None:
        paths = install.get_agent_skill_paths()
        assert isinstance(paths, dict)
        # Should be a copy, not the original
        assert paths is not install.AGENT_SKILL_PATHS

    def test_contains_all_agents(self) -> None:
        paths = install.get_agent_skill_paths()
        assert "claude" in paths
        assert "cursor" in paths
        assert "opencode" in paths
        assert "gemini" in paths


class TestLinkSkillToAgent:
    """Tests for link_skill_to_agent."""

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_creates_symlink(
        self, canonical_skill_dir: Path, tmp_path: Path
    ) -> None:
        symlink = install.link_skill_to_agent("myorg", "myskill", "claude")

        assert symlink.is_symlink()
        assert symlink.resolve() == canonical_skill_dir.resolve()
        assert symlink.name == "myorg--myskill"

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_creates_parent_dirs(
        self, canonical_skill_dir: Path, tmp_path: Path
    ) -> None:
        # The agent skills directory should not exist yet
        agent_dir = install.AGENT_SKILL_PATHS["claude"]
        assert not agent_dir.exists()

        install.link_skill_to_agent("myorg", "myskill", "claude")
        assert agent_dir.exists()

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_replaces_existing_symlink(
        self, canonical_skill_dir: Path, tmp_path: Path
    ) -> None:
        # Create the first symlink
        install.link_skill_to_agent("myorg", "myskill", "claude")

        # Create again -- should not raise
        symlink = install.link_skill_to_agent("myorg", "myskill", "claude")
        assert symlink.is_symlink()
        assert symlink.resolve() == canonical_skill_dir.resolve()

    def test_unknown_agent_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown agent"):
            install.link_skill_to_agent("myorg", "myskill", "nonexistent-agent")

    def test_missing_canonical_dir_raises(self, tmp_path: Path) -> None:
        # Point get_dhub_skill_path to a non-existent directory
        missing = tmp_path / "does" / "not" / "exist"
        with patch.object(install, "get_dhub_skill_path", return_value=missing):
            with pytest.raises(FileNotFoundError, match="not found"):
                install.link_skill_to_agent("myorg", "myskill", "claude")


class TestUnlinkSkillFromAgent:
    """Tests for unlink_skill_from_agent."""

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_removes_symlink(
        self, canonical_skill_dir: Path, tmp_path: Path
    ) -> None:
        symlink = install.link_skill_to_agent("myorg", "myskill", "claude")
        assert symlink.exists()

        install.unlink_skill_from_agent("myorg", "myskill", "claude")
        assert not symlink.exists()

    def test_unknown_agent_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown agent"):
            install.unlink_skill_from_agent("myorg", "myskill", "nonexistent")

    def test_no_symlink_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="No symlink"):
            install.unlink_skill_from_agent("myorg", "myskill", "claude")


class TestLinkSkillToAllAgents:
    """Tests for link_skill_to_all_agents."""

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_links_to_all_agents(
        self, canonical_skill_dir: Path, tmp_path: Path
    ) -> None:
        linked = install.link_skill_to_all_agents("myorg", "myskill")

        assert sorted(linked) == ["claude", "cursor", "gemini", "opencode"]

        # Verify all symlinks exist
        for agent in linked:
            symlink = install.AGENT_SKILL_PATHS[agent] / "myorg--myskill"
            assert symlink.is_symlink()
            assert symlink.resolve() == canonical_skill_dir.resolve()


class TestListLinkedAgents:
    """Tests for list_linked_agents."""

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_returns_linked_agents(
        self, canonical_skill_dir: Path, tmp_path: Path
    ) -> None:
        install.link_skill_to_agent("myorg", "myskill", "claude")
        install.link_skill_to_agent("myorg", "myskill", "cursor")

        linked = install.list_linked_agents("myorg", "myskill")
        assert sorted(linked) == ["claude", "cursor"]

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_returns_empty_when_none_linked(
        self, canonical_skill_dir: Path
    ) -> None:
        linked = install.list_linked_agents("myorg", "myskill")
        assert linked == []
