"""Installation utilities for skills.

Handles checksum verification, canonical path resolution,
and symlink management for linking skills to agent directories.
"""

import hashlib
from pathlib import Path


# Mapping of agent names to their skill directories
AGENT_SKILL_PATHS: dict[str, Path] = {
    "claude": Path.home() / ".claude" / "skills",
    "codex": Path.home() / ".codex" / "skills",
    "cursor": Path.home() / ".cursor" / "skills",
    "opencode": Path.home() / ".config" / "opencode" / "skills",
    "gemini": Path.home() / ".gemini" / "skills",
}


def verify_checksum(data: bytes, expected: str) -> None:
    """Verify that the SHA-256 checksum of data matches the expected value.

    Args:
        data: The raw bytes to hash.
        expected: The expected hex-encoded SHA-256 digest.

    Raises:
        ValueError: If the computed checksum does not match.
    """
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError(
            f"Checksum mismatch: expected {expected}, got {actual}."
        )


def get_dhub_skill_path(org: str, skill: str) -> Path:
    """Return the canonical local path for an installed skill.

    Args:
        org: The organization slug.
        skill: The skill name.

    Returns:
        Path to ~/.dhub/skills/{org}/{skill}/.
    """
    return Path.home() / ".dhub" / "skills" / org / skill


def get_agent_skill_paths() -> dict[str, Path]:
    """Return a copy of the mapping of agent names to their skill directories."""
    return dict(AGENT_SKILL_PATHS)


def link_skill_to_agent(org: str, skill_name: str, agent: str) -> Path:
    """Create a symlink from the agent's skill directory to the canonical skill path.

    The symlink is named {org}--{skill_name} inside the agent's skill directory,
    and points to the canonical path under ~/.dhub/skills/{org}/{skill_name}/.

    Args:
        org: The organization slug.
        skill_name: The skill name.
        agent: The agent name (e.g. "claude", "cursor").

    Returns:
        The path of the created symlink.

    Raises:
        ValueError: If the agent name is not recognized.
        FileNotFoundError: If the canonical skill directory does not exist.
    """
    if agent not in AGENT_SKILL_PATHS:
        raise ValueError(
            f"Unknown agent '{agent}'. Known agents: {', '.join(sorted(AGENT_SKILL_PATHS))}."
        )

    canonical = get_dhub_skill_path(org, skill_name)
    if not canonical.exists():
        raise FileNotFoundError(
            f"Skill directory not found: {canonical}"
        )

    agent_dir = AGENT_SKILL_PATHS[agent]
    agent_dir.mkdir(parents=True, exist_ok=True)

    symlink_path = agent_dir / f"{org}--{skill_name}"

    # Remove existing symlink if present to allow re-linking
    if symlink_path.is_symlink() or symlink_path.exists():
        symlink_path.unlink()

    symlink_path.symlink_to(canonical)
    return symlink_path


def unlink_skill_from_agent(org: str, skill_name: str, agent: str) -> None:
    """Remove the symlink for a skill from an agent's directory.

    Args:
        org: The organization slug.
        skill_name: The skill name.
        agent: The agent name.

    Raises:
        ValueError: If the agent name is not recognized.
        FileNotFoundError: If no symlink exists for this skill/agent combination.
    """
    if agent not in AGENT_SKILL_PATHS:
        raise ValueError(
            f"Unknown agent '{agent}'. Known agents: {', '.join(sorted(AGENT_SKILL_PATHS))}."
        )

    symlink_path = AGENT_SKILL_PATHS[agent] / f"{org}--{skill_name}"

    if not symlink_path.is_symlink() and not symlink_path.exists():
        raise FileNotFoundError(
            f"No symlink found at {symlink_path}"
        )

    symlink_path.unlink()


def link_skill_to_all_agents(org: str, skill_name: str) -> list[str]:
    """Symlink a skill to all known agent directories.

    Args:
        org: The organization slug.
        skill_name: The skill name.

    Returns:
        List of agent names that were successfully linked.
    """
    linked: list[str] = []
    for agent in sorted(AGENT_SKILL_PATHS):
        link_skill_to_agent(org, skill_name, agent)
        linked.append(agent)
    return linked


def list_linked_agents(org: str, skill_name: str) -> list[str]:
    """Check which agents have a symlink for this skill.

    Args:
        org: The organization slug.
        skill_name: The skill name.

    Returns:
        List of agent names that have a symlink pointing to this skill.
    """
    canonical = get_dhub_skill_path(org, skill_name)
    linked: list[str] = []

    for agent, agent_dir in sorted(AGENT_SKILL_PATHS.items()):
        symlink_path = agent_dir / f"{org}--{skill_name}"
        if symlink_path.is_symlink() and symlink_path.resolve() == canonical.resolve():
            linked.append(agent)

    return linked
