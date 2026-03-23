"""Installation utilities for skills.

Handles checksum verification, canonical path resolution,
version tracking, and symlink management for linking skills
to agent directories.
"""

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

# Filename used to track the installed version inside each skill directory.
_VERSION_FILE = ".dhub-version"

# Mapping of agent --agent flag values to their global skill directories.
# Each key is the CLI argument for `dhub install --agent <key>`.
AGENT_SKILL_PATHS: dict[str, Path] = {
    "adal": Path.home() / ".adal" / "skills",
    "amp": Path.home() / ".config" / "agents" / "skills",
    "antigravity": Path.home() / ".gemini" / "antigravity" / "skills",
    "augment": Path.home() / ".augment" / "skills",
    "claude-code": Path.home() / ".claude" / "skills",
    "cline": Path.home() / ".cline" / "skills",
    "codebuddy": Path.home() / ".codebuddy" / "skills",
    "codex": Path.home() / ".codex" / "skills",
    "command-code": Path.home() / ".commandcode" / "skills",
    "continue": Path.home() / ".continue" / "skills",
    "cortex": Path.home() / ".snowflake" / "cortex" / "skills",
    "crush": Path.home() / ".config" / "crush" / "skills",
    "cursor": Path.home() / ".cursor" / "skills",
    "droid": Path.home() / ".factory" / "skills",
    "gemini-cli": Path.home() / ".gemini" / "skills",
    "github-copilot": Path.home() / ".copilot" / "skills",
    "goose": Path.home() / ".config" / "goose" / "skills",
    "iflow-cli": Path.home() / ".iflow" / "skills",
    "junie": Path.home() / ".junie" / "skills",
    "kilo": Path.home() / ".kilocode" / "skills",
    "kimi-cli": Path.home() / ".config" / "agents" / "skills",
    "kiro-cli": Path.home() / ".kiro" / "skills",
    "kode": Path.home() / ".kode" / "skills",
    "mcpjam": Path.home() / ".mcpjam" / "skills",
    "mistral-vibe": Path.home() / ".vibe" / "skills",
    "mux": Path.home() / ".mux" / "skills",
    "neovate": Path.home() / ".neovate" / "skills",
    "openclaw": Path.home() / ".openclaw" / "skills",
    "opencode": Path.home() / ".config" / "opencode" / "skills",
    "openhands": Path.home() / ".openhands" / "skills",
    "pi": Path.home() / ".pi" / "agent" / "skills",
    "pochi": Path.home() / ".pochi" / "skills",
    "qoder": Path.home() / ".qoder" / "skills",
    "qwen-code": Path.home() / ".qwen" / "skills",
    "replit": Path.home() / ".config" / "agents" / "skills",
    "roo": Path.home() / ".roo" / "skills",
    "trae": Path.home() / ".trae" / "skills",
    "trae-cn": Path.home() / ".trae-cn" / "skills",
    "universal": Path.home() / ".config" / "agents" / "skills",
    "windsurf": Path.home() / ".codeium" / "windsurf" / "skills",
    "zencoder": Path.home() / ".zencoder" / "skills",
}


def compute_checksum(data: bytes) -> str:
    """Compute SHA-256 hex digest of data."""
    return hashlib.sha256(data).hexdigest()


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
        raise ValueError(f"Checksum mismatch: expected {expected}, got {actual}.")


def get_skills_root() -> Path:
    """Return the root directory for all installed skills (~/.dhub/skills/)."""
    return Path.home() / ".dhub" / "skills"


def get_dhub_skill_path(org: str, skill: str) -> Path:
    """Return the canonical local path for an installed skill.

    Args:
        org: The organization slug.
        skill: The skill name.

    Returns:
        Path to ~/.dhub/skills/{org}/{skill}/.
    """
    return get_skills_root() / org / skill


def get_agent_skill_paths() -> dict[str, Path]:
    """Return a copy of the mapping of agent names to their skill directories."""
    return dict(AGENT_SKILL_PATHS)


def link_skill_to_agent(org: str, skill_name: str, agent: str) -> Path:
    """Create a symlink from the agent's skill directory to the canonical skill path.

    The symlink is named {skill_name} inside the agent's skill directory,
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
        raise ValueError(f"Unknown agent '{agent}'. Known agents: {', '.join(sorted(AGENT_SKILL_PATHS))}.")

    canonical = get_dhub_skill_path(org, skill_name)
    if not canonical.exists():
        raise FileNotFoundError(f"Skill directory not found: {canonical}")

    agent_dir = AGENT_SKILL_PATHS[agent]
    agent_dir.mkdir(parents=True, exist_ok=True)

    symlink_path = agent_dir / skill_name

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
        raise ValueError(f"Unknown agent '{agent}'. Known agents: {', '.join(sorted(AGENT_SKILL_PATHS))}.")

    symlink_path = AGENT_SKILL_PATHS[agent] / skill_name

    if not symlink_path.is_symlink() and not symlink_path.exists():
        raise FileNotFoundError(f"No symlink found at {symlink_path}")

    symlink_path.unlink()


def link_skill_to_all_agents(org: str, skill_name: str) -> list[str]:
    """Symlink a skill to all known agent directories.

    Multiple agents can share the same directory (e.g. amp, kimi-cli, replit,
    universal all use ~/.config/agents/skills). Each unique physical path is
    only symlinked once to avoid needless delete-recreate cycles.

    Args:
        org: The organization slug.
        skill_name: The skill name.

    Returns:
        List of agent names that were successfully linked.
    """
    linked: list[str] = []
    seen_paths: set[Path] = set()
    for agent in sorted(AGENT_SKILL_PATHS):
        agent_dir = AGENT_SKILL_PATHS[agent]
        symlink_path = agent_dir / skill_name
        if symlink_path in seen_paths:
            linked.append(agent)
            continue
        link_skill_to_agent(org, skill_name, agent)
        seen_paths.add(symlink_path)
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
        symlink_path = agent_dir / skill_name
        if symlink_path.is_symlink() and symlink_path.resolve() == canonical.resolve():
            linked.append(agent)

    return linked


@dataclass(frozen=True)
class InstalledVersion:
    """Metadata recorded when a skill is installed, used by ``dhub update``."""

    version: str
    allow_risky: bool = False


def save_installed_version(org: str, skill_name: str, version: str, *, allow_risky: bool = False) -> None:
    """Write the installed version to the skill's canonical directory.

    Creates a `.dhub-version` JSON file so that ``dhub update`` can compare
    against the registry and preserve the original install flags.
    """
    path = get_dhub_skill_path(org, skill_name) / _VERSION_FILE
    data = {"version": version, "allow_risky": allow_risky}
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")


def get_installed_version(org: str, skill_name: str) -> InstalledVersion | None:
    """Read the installed version from the skill's canonical directory.

    Returns an ``InstalledVersion``, or ``None`` if no version file exists
    (legacy install).
    """
    path = get_dhub_skill_path(org, skill_name) / _VERSION_FILE
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    try:
        data = json.loads(raw)
        return InstalledVersion(
            version=data["version"],
            allow_risky=data.get("allow_risky", False),
        )
    except (json.JSONDecodeError, KeyError):
        # Fallback for plain-text version files (shouldn't exist in practice
        # since this format ships with the same PR, but be defensive).
        return InstalledVersion(version=raw)


def list_installed_skills() -> list[tuple[str, str]]:
    """Scan ~/.dhub/skills/ and return all installed (org, skill) pairs.

    Only directories that look like valid skill installs (contain at
    least one file) are included.
    """
    skills_root = get_skills_root()
    if not skills_root.exists():
        return []
    installed: list[tuple[str, str]] = []
    for org_dir in sorted(skills_root.iterdir()):
        if not org_dir.is_dir():
            continue
        for skill_dir in sorted(org_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            # Skip empty directories left over from partial uninstalls
            if not any(skill_dir.iterdir()):
                continue
            installed.append((org_dir.name, skill_dir.name))
    return installed


def uninstall_skill(org: str, skill_name: str) -> list[str]:
    """Remove a locally installed skill and all its agent symlinks.

    Removes symlinks from all agent directories first, then deletes the
    canonical skill directory under ~/.dhub/skills/{org}/{skill_name}.

    Args:
        org: The organization slug.
        skill_name: The skill name.

    Returns:
        List of agent names whose symlinks were removed.

    Raises:
        FileNotFoundError: If the skill is not installed locally.
    """
    canonical = get_dhub_skill_path(org, skill_name)
    if not canonical.exists():
        raise FileNotFoundError(f"Skill not installed: {canonical}")

    # Remove agent symlinks first.
    # Multiple agents can share the same directory (e.g. amp, kimi-cli, replit,
    # universal all use ~/.config/agents/skills). Track which physical symlink
    # paths have already been removed to avoid FileNotFoundError on duplicates.
    unlinked: list[str] = []
    removed_paths: set[Path] = set()
    for agent in list_linked_agents(org, skill_name):
        symlink_path = AGENT_SKILL_PATHS[agent] / skill_name
        if symlink_path in removed_paths:
            unlinked.append(agent)
            continue
        unlink_skill_from_agent(org, skill_name, agent)
        removed_paths.add(symlink_path)
        unlinked.append(agent)

    # Remove the skill directory
    shutil.rmtree(canonical)

    # Clean up empty org directory
    org_dir = canonical.parent
    if org_dir.exists() and not any(org_dir.iterdir()):
        org_dir.rmdir()

    return unlinked
