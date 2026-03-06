"""Plugin manifest parser and platform detector.

Parses plugin.json files from .*-plugin/ directories and discovers
plugin components (skills, hooks, agents, commands) from the directory
structure. Platform-agnostic: supports Claude, Cursor, Codex, and any
future agent platform using the .*-plugin/ convention.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from dhub_core.manifest import parse_skill_md
from dhub_core.models import SkillManifest

PLUGIN_DIR_PATTERN = re.compile(r"^\.(\w+)-plugin$")

# Preference order for picking the primary manifest when multiple platforms exist.
_PLATFORM_PREFERENCE = ("claude", "cursor", "codex")


@dataclass(frozen=True)
class PluginSkillRef:
    """Reference to a skill contained within a plugin."""

    name: str
    description: str
    path: str


@dataclass(frozen=True)
class PluginHookRef:
    """Reference to a hook defined in a plugin."""

    event: str
    command: str
    is_async: bool


@dataclass(frozen=True)
class PluginManifest:
    """Parsed plugin manifest with discovered components."""

    name: str
    description: str
    version: str
    author_name: str | None
    author_email: str | None
    homepage: str | None
    repository: str | None
    license: str | None
    keywords: tuple[str, ...]
    platforms: tuple[str, ...]
    skills: tuple[PluginSkillRef, ...]
    hooks: tuple[PluginHookRef, ...]
    agents: tuple[str, ...]
    commands: tuple[str, ...]


def detect_plugin_platforms(root: Path) -> list[str]:
    """Scan root for .*-plugin/ directories containing plugin.json.

    Returns sorted list of platform names (e.g. ["claude", "cursor"]).
    """
    platforms = []
    for entry in root.iterdir():
        if entry.is_dir():
            m = PLUGIN_DIR_PATTERN.match(entry.name)
            if m and (entry / "plugin.json").exists():
                platforms.append(m.group(1))
    return sorted(platforms)


def _pick_primary_platform(platforms: list[str]) -> str:
    """Pick the primary platform based on preference order."""
    for preferred in _PLATFORM_PREFERENCE:
        if preferred in platforms:
            return preferred
    return platforms[0]


def _read_plugin_json(root: Path, platform: str) -> dict:
    """Read and parse plugin.json for a specific platform."""
    path = root / f".{platform}-plugin" / "plugin.json"
    return json.loads(path.read_text())


def _discover_skills(root: Path) -> tuple[PluginSkillRef, ...]:
    """Discover skills in the skills/ directory by looking for SKILL.md files."""
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        return ()

    refs: list[PluginSkillRef] = []
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        try:
            manifest: SkillManifest = parse_skill_md(skill_md)
            refs.append(
                PluginSkillRef(
                    name=manifest.name,
                    description=manifest.description,
                    path=str(skill_dir.relative_to(root)),
                )
            )
        except (ValueError, FileNotFoundError):
            # Skip unparseable skills — they'll be flagged by the gauntlet
            continue
    return tuple(refs)


def _discover_hooks(root: Path) -> tuple[PluginHookRef, ...]:
    """Discover hooks from hooks/hooks.json."""
    refs: list[PluginHookRef] = []
    hooks_files: list[Path] = []

    # Check root-level hooks/
    root_hooks = root / "hooks" / "hooks.json"
    if root_hooks.exists():
        hooks_files.append(root_hooks)

    # Check each platform dir
    for entry in root.iterdir():
        if entry.is_dir() and PLUGIN_DIR_PATTERN.match(entry.name):
            platform_hooks = entry / "hooks.json"
            if platform_hooks.exists():
                hooks_files.append(platform_hooks)

    seen: set[tuple[str, str]] = set()
    for hooks_file in hooks_files:
        try:
            data = json.loads(hooks_file.read_text())
        except (json.JSONDecodeError, ValueError):
            continue
        hooks_map = data.get("hooks", {})
        for event, hook_entries in hooks_map.items():
            for entry in hook_entries:
                for hook in entry.get("hooks", []):
                    command = hook.get("command", "")
                    key = (event, command)
                    if key not in seen:
                        seen.add(key)
                        refs.append(
                            PluginHookRef(
                                event=event,
                                command=command,
                                is_async=hook.get("async", False),
                            )
                        )
    return tuple(refs)


def _discover_agents(root: Path) -> tuple[str, ...]:
    """Discover agent definitions from agents/ directory."""
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return ()
    return tuple(sorted(p.stem for p in agents_dir.iterdir() if p.is_file() and p.suffix == ".md"))


def _discover_commands(root: Path) -> tuple[str, ...]:
    """Discover command definitions from commands/ directory."""
    commands_dir = root / "commands"
    if not commands_dir.is_dir():
        return ()
    return tuple(sorted(p.stem for p in commands_dir.iterdir() if p.is_file() and p.suffix == ".md"))


def parse_plugin_manifest(root: Path) -> PluginManifest:
    """Parse a plugin from a directory containing .*-plugin/ dirs.

    Reads the primary platform's plugin.json for metadata.
    Discovers skills, hooks, agents, and commands from directory structure.

    Raises:
        ValueError: If no plugin platform directories are found.
    """
    platforms = detect_plugin_platforms(root)
    if not platforms:
        raise ValueError(f"No plugin platform directories found in {root}")

    primary_platform = _pick_primary_platform(platforms)
    data = _read_plugin_json(root, primary_platform)

    author = data.get("author", {})
    if isinstance(author, dict):
        author_name = author.get("name")
        author_email = author.get("email")
    else:
        author_name = None
        author_email = None

    keywords_raw = data.get("keywords", [])

    name = data.get("name")
    if not name:
        raise ValueError("plugin.json missing required 'name' field")
    return PluginManifest(
        name=name,
        description=data.get("description", ""),
        version=data.get("version", "0.0.0"),
        author_name=author_name,
        author_email=author_email,
        homepage=data.get("homepage"),
        repository=data.get("repository"),
        license=data.get("license"),
        keywords=tuple(keywords_raw) if isinstance(keywords_raw, list) else (),
        platforms=tuple(platforms),
        skills=_discover_skills(root),
        hooks=_discover_hooks(root),
        agents=_discover_agents(root),
        commands=_discover_commands(root),
    )
