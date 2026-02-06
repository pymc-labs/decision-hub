"""SKILL.md parser and validator.

Parses SKILL.md files containing YAML frontmatter between --- delimiters
followed by a markdown body that serves as the agent system prompt.
"""

import re
from pathlib import Path

import yaml

from decision_hub.models import (
    AgentTestTarget,
    RuntimeConfig,
    SkillManifest,
    TestingConfig,
)

# Name: 1-64 chars, lowercase alphanumeric + hyphens, no leading/trailing hyphens.
# Aligned with domain/publish.py _SKILL_NAME_PATTERN.
_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")


def parse_skill_md(path: Path) -> SkillManifest:
    """Parse a SKILL.md file into a SkillManifest.

    The file format is YAML frontmatter between --- delimiters,
    followed by the markdown body (the agent system prompt).

    Raises:
        ValueError: If the file format is invalid or required fields are missing.
        FileNotFoundError: If the path does not exist.
    """
    content = path.read_text()
    frontmatter_str, body = _split_frontmatter(content)
    data = yaml.safe_load(frontmatter_str)

    if not isinstance(data, dict):
        raise ValueError("Frontmatter must be a YAML mapping.")

    # Required fields
    name = data.get("name")
    if not name:
        raise ValueError("Required field 'name' is missing.")
    if not isinstance(name, str) or not _NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid name '{name}': must be 1-64 chars, lowercase "
            "alphanumeric + hyphens, no leading/trailing hyphens."
        )

    description = data.get("description")
    if not description:
        raise ValueError("Required field 'description' is missing.")
    if not isinstance(description, str) or len(description) > 1024:
        raise ValueError(
            "Description must be a string of 1-1024 characters."
        )

    # Optional scalar fields
    license_val = data.get("license")
    compatibility = data.get("compatibility")
    metadata = data.get("metadata")
    allowed_tools = data.get("allowed_tools")

    # Optional structured blocks
    runtime = _parse_runtime(data.get("runtime"))
    testing = _parse_testing(data.get("testing"))
    manifest = SkillManifest(
        name=name,
        description=description,
        license=license_val,
        compatibility=compatibility,
        metadata=metadata,
        allowed_tools=allowed_tools,
        runtime=runtime,
        testing=testing,
        body=body,
    )

    errors = validate_manifest(manifest)
    if errors:
        raise ValueError(
            "Manifest validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    return manifest


def _split_frontmatter(content: str) -> tuple[str, str]:
    """Split SKILL.md content into frontmatter string and body.

    Expects the file to start with --- on its own line, followed by
    YAML content, then another --- on its own line, then the body.
    Uses line-based matching so that --- in the body (e.g. markdown
    horizontal rules) does not break parsing.
    """
    lines = content.split("\n")

    # Skip leading blank lines
    start = 0
    while start < len(lines) and lines[start].strip() == "":
        start += 1

    if start >= len(lines) or lines[start].strip() != "---":
        raise ValueError(
            "SKILL.md must start with --- to begin YAML frontmatter."
        )

    # Find the closing --- delimiter (must be on its own line)
    close = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "---":
            close = i
            break

    if close is None:
        raise ValueError(
            "SKILL.md must have closing --- delimiter after frontmatter."
        )

    frontmatter_str = "\n".join(lines[start + 1 : close])
    body = "\n".join(lines[close + 1 :]).strip()
    return frontmatter_str, body


def _parse_runtime(data: dict | None) -> RuntimeConfig | None:
    """Parse the runtime block from frontmatter."""
    if data is None:
        return None

    if not isinstance(data, dict):
        raise ValueError("'runtime' must be a mapping.")

    driver = data.get("driver")
    if not driver or not isinstance(driver, str):
        raise ValueError("runtime.driver is required and must be a string.")

    entrypoint = data.get("entrypoint")
    if not entrypoint or not isinstance(entrypoint, str):
        raise ValueError("runtime.entrypoint is required and must be a string.")

    lockfile = data.get("lockfile")
    if not lockfile or not isinstance(lockfile, str):
        raise ValueError("runtime.lockfile is required and must be a string.")

    env_raw = data.get("env", [])
    if not isinstance(env_raw, list):
        raise ValueError("runtime.env must be a list of strings.")
    env = tuple(str(e) for e in env_raw)

    return RuntimeConfig(
        driver=driver,
        entrypoint=entrypoint,
        lockfile=lockfile,
        env=env,
    )


def _parse_testing(data: dict | None) -> TestingConfig | None:
    """Parse the testing block from frontmatter."""
    if data is None:
        return None

    if not isinstance(data, dict):
        raise ValueError("'testing' must be a mapping.")

    cases = data.get("cases")
    if not cases or not isinstance(cases, str):
        raise ValueError("testing.cases is required and must be a string.")

    agents_raw = data.get("agents", [])
    if not isinstance(agents_raw, list):
        raise ValueError("testing.agents must be a list.")

    agents = tuple(_parse_agent_target(a) for a in agents_raw)

    return TestingConfig(cases=cases, agents=agents)


def _parse_agent_target(data: dict) -> AgentTestTarget:
    """Parse a single agent test target from the testing.agents list."""
    if not isinstance(data, dict):
        raise ValueError("Each agent target must be a mapping.")

    name = data.get("name")
    if not name or not isinstance(name, str):
        raise ValueError("Agent target 'name' is required.")

    keys_raw = data.get("required_keys", [])
    if not isinstance(keys_raw, list):
        raise ValueError("Agent target 'required_keys' must be a list.")

    return AgentTestTarget(
        name=name,
        required_keys=tuple(str(k) for k in keys_raw),
    )


def extract_description(content: str) -> str:
    """Extract the description field from SKILL.md content.

    Parses the YAML frontmatter and returns the description string.
    Falls back to regex extraction when YAML parsing fails (e.g. when
    the description contains unquoted colons).
    Returns an empty string if the description is missing.
    """
    try:
        frontmatter_str, _ = _split_frontmatter(content)
    except ValueError:
        return ""

    # Try standard YAML parsing first
    try:
        data = yaml.safe_load(frontmatter_str)
        if isinstance(data, dict):
            desc = data.get("description")
            return str(desc) if desc else ""
    except yaml.YAMLError:
        pass

    # Fallback: extract description line directly via regex.
    # Handles values with unquoted YAML-special characters like colons.
    match = re.search(r"^description:\s*(.+)$", frontmatter_str, re.MULTILINE)
    if match:
        return match.group(1).strip()

    return ""


def validate_manifest(manifest: SkillManifest) -> list[str]:
    """Validate a parsed manifest. Returns list of error messages (empty = valid)."""
    errors: list[str] = []

    if not _NAME_PATTERN.match(manifest.name):
        errors.append(
            f"Invalid name '{manifest.name}': must be 1-64 chars, lowercase "
            "alphanumeric + hyphens, no leading/trailing hyphens."
        )

    if not manifest.description or len(manifest.description) > 1024:
        errors.append("Description must be 1-1024 characters.")

    if not manifest.body:
        errors.append("Body (system prompt) must not be empty.")

    if manifest.runtime and manifest.runtime.driver not in ("local/uv",):
        errors.append(
            f"Unsupported runtime driver '{manifest.runtime.driver}'. "
            "Supported: local/uv"
        )

    return errors
