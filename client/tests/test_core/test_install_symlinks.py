"""Tests for symlink management in install module."""

from pathlib import Path
from unittest.mock import patch

import pytest

from dhub.core import install


@pytest.fixture(autouse=True)
def _mock_agent_paths(tmp_path: Path) -> None:
    """Override AGENT_SKILL_PATHS to use temp directories for all tests.

    Uses a representative subset of agents covering different path structures
    (simple, nested, shared directories).
    """
    mock_paths = {
        "claude-code": tmp_path / "agents" / "claude-code" / "skills",
        "cursor": tmp_path / "agents" / "cursor" / "skills",
        "opencode": tmp_path / "agents" / "opencode" / "skills",
        "gemini-cli": tmp_path / "agents" / "gemini-cli" / "skills",
        "windsurf": tmp_path / "agents" / "windsurf" / "skills",
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
        assert "claude-code" in paths
        assert "cursor" in paths
        assert "opencode" in paths
        assert "gemini-cli" in paths
        assert "windsurf" in paths


class TestLinkSkillToAgent:
    """Tests for link_skill_to_agent."""

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_creates_symlink(self, canonical_skill_dir: Path, tmp_path: Path) -> None:
        symlink = install.link_skill_to_agent("myorg", "myskill", "claude-code")

        assert symlink.is_symlink()
        assert symlink.resolve() == canonical_skill_dir.resolve()
        assert symlink.name == "myskill"

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_creates_parent_dirs(self, canonical_skill_dir: Path, tmp_path: Path) -> None:
        # The agent skills directory should not exist yet
        agent_dir = install.AGENT_SKILL_PATHS["claude-code"]
        assert not agent_dir.exists()

        install.link_skill_to_agent("myorg", "myskill", "claude-code")
        assert agent_dir.exists()

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_replaces_existing_symlink(self, canonical_skill_dir: Path, tmp_path: Path) -> None:
        # Create the first symlink
        install.link_skill_to_agent("myorg", "myskill", "claude-code")

        # Create again -- should not raise
        symlink = install.link_skill_to_agent("myorg", "myskill", "claude-code")
        assert symlink.is_symlink()
        assert symlink.resolve() == canonical_skill_dir.resolve()

    def test_unknown_agent_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown agent"):
            install.link_skill_to_agent("myorg", "myskill", "nonexistent-agent")

    def test_missing_canonical_dir_raises(self, tmp_path: Path) -> None:
        # Point get_dhub_skill_path to a non-existent directory
        missing = tmp_path / "does" / "not" / "exist"
        with (
            patch.object(install, "get_dhub_skill_path", return_value=missing),
            pytest.raises(FileNotFoundError, match="not found"),
        ):
            install.link_skill_to_agent("myorg", "myskill", "claude-code")


class TestUnlinkSkillFromAgent:
    """Tests for unlink_skill_from_agent."""

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_removes_symlink(self, canonical_skill_dir: Path, tmp_path: Path) -> None:
        symlink = install.link_skill_to_agent("myorg", "myskill", "claude-code")
        assert symlink.exists()

        install.unlink_skill_from_agent("myorg", "myskill", "claude-code")
        assert not symlink.exists()

    def test_unknown_agent_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown agent"):
            install.unlink_skill_from_agent("myorg", "myskill", "nonexistent")

    def test_no_symlink_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="No symlink"):
            install.unlink_skill_from_agent("myorg", "myskill", "claude-code")


class TestIsAgentPresent:
    """Tests for is_agent_present."""

    def test_present_when_parent_exists(self, tmp_path: Path) -> None:
        # The parent of the skills dir (e.g. ~/.claude) must exist
        agent_dir = install.AGENT_SKILL_PATHS["claude-code"]
        agent_dir.parent.mkdir(parents=True, exist_ok=True)
        assert install.is_agent_present("claude-code") is True

    def test_absent_when_parent_missing(self) -> None:
        # No parent dirs created → agent not present
        assert install.is_agent_present("claude-code") is False

    def test_unknown_agent(self) -> None:
        assert install.is_agent_present("nonexistent-agent") is False


class TestLinkSkillToAllAgents:
    """Tests for link_skill_to_all_agents."""

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_links_only_to_present_agents(self, canonical_skill_dir: Path, tmp_path: Path) -> None:
        # Mark only claude-code and cursor as present
        install.AGENT_SKILL_PATHS["claude-code"].parent.mkdir(parents=True, exist_ok=True)
        install.AGENT_SKILL_PATHS["cursor"].parent.mkdir(parents=True, exist_ok=True)

        linked, skipped = install.link_skill_to_all_agents("myorg", "myskill")

        assert sorted(linked) == ["claude-code", "cursor"]
        assert sorted(skipped) == ["gemini-cli", "opencode", "windsurf"]

        # Verify symlinks exist only for present agents
        for agent in linked:
            symlink = install.AGENT_SKILL_PATHS[agent] / "myskill"
            assert symlink.is_symlink()
            assert symlink.resolve() == canonical_skill_dir.resolve()

        # Verify no symlinks for skipped agents
        for agent in skipped:
            symlink = install.AGENT_SKILL_PATHS[agent] / "myskill"
            assert not symlink.exists()

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_links_to_all_when_all_present(self, canonical_skill_dir: Path, tmp_path: Path) -> None:
        # Mark all agents as present
        for agent_dir in install.AGENT_SKILL_PATHS.values():
            agent_dir.parent.mkdir(parents=True, exist_ok=True)

        linked, skipped = install.link_skill_to_all_agents("myorg", "myskill")

        assert sorted(linked) == ["claude-code", "cursor", "gemini-cli", "opencode", "windsurf"]
        assert skipped == []

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_skips_all_when_none_present(self, canonical_skill_dir: Path, tmp_path: Path) -> None:
        linked, skipped = install.link_skill_to_all_agents("myorg", "myskill")

        assert linked == []
        assert sorted(skipped) == ["claude-code", "cursor", "gemini-cli", "opencode", "windsurf"]


class TestUninstallSharedPaths:
    """Tests for uninstall_skill with agents sharing the same directory."""

    def test_uninstall_with_shared_agent_paths(self, tmp_path: Path) -> None:
        """Agents sharing a path (e.g. amp, kimi-cli) must not crash on uninstall."""
        shared_dir = tmp_path / "agents" / "shared" / "skills"
        mock_paths = {
            "agent-a": shared_dir,
            "agent-b": shared_dir,
            "agent-c": tmp_path / "agents" / "unique" / "skills",
        }
        canonical = tmp_path / ".dhub" / "skills" / "myorg" / "myskill"
        canonical.mkdir(parents=True)
        (canonical / "SKILL.md").write_text("# Skill content")

        # Create parent dirs so agents are detected as present
        shared_dir.parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "agents" / "unique").mkdir(parents=True, exist_ok=True)

        with (
            patch.object(install, "AGENT_SKILL_PATHS", mock_paths),
            patch.object(install, "get_dhub_skill_path", return_value=canonical),
        ):
            # Link to all agents — shared path gets one physical symlink
            install.link_skill_to_all_agents("myorg", "myskill")

            # Uninstall must not crash despite agent-a and agent-b sharing a symlink
            unlinked = install.uninstall_skill("myorg", "myskill")

            assert sorted(unlinked) == ["agent-a", "agent-b", "agent-c"]
            assert not canonical.exists()


class TestListLinkedAgents:
    """Tests for list_linked_agents."""

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_returns_linked_agents(self, canonical_skill_dir: Path, tmp_path: Path) -> None:
        install.link_skill_to_agent("myorg", "myskill", "claude-code")
        install.link_skill_to_agent("myorg", "myskill", "cursor")

        linked = install.list_linked_agents("myorg", "myskill")
        assert sorted(linked) == ["claude-code", "cursor"]

    @pytest.mark.usefixtures("_mock_dhub_path")
    def test_returns_empty_when_none_linked(self, canonical_skill_dir: Path) -> None:
        linked = install.list_linked_agents("myorg", "myskill")
        assert linked == []
