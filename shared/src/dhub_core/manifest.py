"""SKILL.md parser and validator.

Parses SKILL.md files containing YAML frontmatter between --- delimiters
followed by a markdown body that serves as the agent system prompt.

This is the single source of truth for manifest parsing — both the
client (dhub-cli) and server (decision-hub-server) depend on this module.
"""

import re
from pathlib import Path

import yaml

from dhub_core.models import (
    AgentTestTarget,
    DependencySpec,
    EvalConfig,
    RuntimeConfig,
    SkillManifest,
    TestingConfig,
)

# Name: 1-64 chars, lowercase alphanumeric + hyphens, no leading/trailing hyphens.
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
    frontmatter_str, body = split_frontmatter(content)
    data = parse_frontmatter_yaml(frontmatter_str)

    if not isinstance(data, dict):
        raise ValueError("Frontmatter must be a YAML mapping.")

    # Required fields
    name = data.get("name")
    if not name:
        raise ValueError("Required field 'name' is missing.")
    if not isinstance(name, str) or not _NAME_PATTERN.match(name):
        raise ValueError(
            f"Invalid name '{name}': must be 1-64 chars, lowercase alphanumeric + hyphens, no leading/trailing hyphens."
        )

    description = data.get("description")
    if not description:
        raise ValueError("Required field 'description' is missing.")
    if not isinstance(description, str) or len(description) > 1024:
        raise ValueError("Description must be a string of 1-1024 characters.")

    # Optional scalar fields
    license_val = data.get("license")
    compatibility = data.get("compatibility")
    metadata = data.get("metadata")
    allowed_tools = data.get("allowed_tools")

    # Optional structured blocks
    runtime = parse_runtime(data.get("runtime"))
    evals = parse_evals(data.get("evals"))
    testing = parse_testing(data.get("testing"))  # Legacy
    manifest = SkillManifest(
        name=name,
        description=description,
        license=license_val,
        compatibility=compatibility,
        metadata=metadata,
        allowed_tools=allowed_tools,
        runtime=runtime,
        evals=evals,
        body=body,
        testing=testing,
    )

    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("Manifest validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

    return manifest


def parse_frontmatter_yaml(frontmatter_str: str) -> dict:
    """Parse YAML frontmatter with a fallback for unquoted special characters.

    Descriptions often contain colons which break standard YAML parsing.
    When yaml.safe_load fails, falls back to line-by-line regex extraction
    for the top-level scalar fields (name, description), then re-parses
    the remaining structured blocks.
    """
    try:
        return yaml.safe_load(frontmatter_str)
    except yaml.YAMLError:
        pass

    # Fallback: extract fields via regex, quoting problematic values
    lines = frontmatter_str.split("\n")
    patched: list[str] = []
    for line in lines:
        # Match top-level scalar fields whose values contain unquoted colons
        m = re.match(r"^(name|description):\s*(.+)$", line)
        if m and ":" in m.group(2):
            patched.append(f'{m.group(1)}: "{m.group(2)}"')
        else:
            patched.append(line)

    patched_str = "\n".join(patched)
    return yaml.safe_load(patched_str)


def split_frontmatter(content: str) -> tuple[str, str]:
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
        raise ValueError("SKILL.md must start with --- to begin YAML frontmatter.")

    # Find the closing --- delimiter (must be on its own line)
    close = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "---":
            close = i
            break

    if close is None:
        raise ValueError("SKILL.md must have closing --- delimiter after frontmatter.")

    frontmatter_str = "\n".join(lines[start + 1 : close])
    body = "\n".join(lines[close + 1 :]).strip()
    return frontmatter_str, body


def parse_runtime(data: dict | None) -> RuntimeConfig | None:
    """Parse the runtime block from frontmatter (soft contract).

    Soft contract: accepts either old hard-coded formats (driver/entrypoint/lockfile)
    or new flexible language/entrypoint + optional dependencies.
    """
    if data is None:
        return None

    if not isinstance(data, dict):
        raise ValueError("'runtime' must be a mapping.")

    # Detect format: presence of 'language' indicates new soft contract
    language = data.get("language")
    if language:
        # New soft contract format
        entrypoint = data.get("entrypoint")
        if not entrypoint or not isinstance(entrypoint, str):
            raise ValueError("runtime.entrypoint is required and must be a string.")

        version_hint = data.get("version_hint")

        env_raw = data.get("env", [])
        if not isinstance(env_raw, list):
            raise ValueError("runtime.env must be a list of strings.")
        env = tuple(str(e) for e in env_raw)

        capabilities_raw = data.get("capabilities", [])
        if not isinstance(capabilities_raw, list):
            raise ValueError("runtime.capabilities must be a list of strings.")
        capabilities = tuple(str(c) for c in capabilities_raw)

        dependencies = parse_dependencies(data.get("dependencies"))
        repair_strategy = data.get("repair_strategy", "attempt_install")

        return RuntimeConfig(
            language=language,
            entrypoint=entrypoint,
            version_hint=version_hint,
            env=env,
            capabilities=capabilities,
            dependencies=dependencies,
            repair_strategy=repair_strategy,
        )
    else:
        # Old hard-coded format (backward compatibility)
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

        # Map old driver format to new language field
        language_map = {"local/uv": "python"}
        language = language_map.get(driver, driver)

        # Build dependencies from old lockfile field
        dependencies = DependencySpec(
            system=(),
            package_manager="uv",
            packages=(),
            lockfile=lockfile,
        )

        return RuntimeConfig(
            language=language,
            entrypoint=entrypoint,
            version_hint=None,
            env=env,
            capabilities=(),
            dependencies=dependencies,
            repair_strategy="attempt_install",
        )


def parse_dependencies(data: dict | None) -> DependencySpec | None:
    """Parse the dependencies block from runtime config."""
    if data is None:
        return None

    if not isinstance(data, dict):
        raise ValueError("'dependencies' must be a mapping.")

    system_raw = data.get("system", [])
    if not isinstance(system_raw, list):
        raise ValueError("dependencies.system must be a list of strings.")
    system = tuple(str(s) for s in system_raw)

    package_manager = data.get("package_manager", "")
    if not isinstance(package_manager, str):
        raise ValueError("dependencies.package_manager must be a string.")

    packages_raw = data.get("packages", [])
    if not isinstance(packages_raw, list):
        raise ValueError("dependencies.packages must be a list of strings.")
    packages = tuple(str(p) for p in packages_raw)

    lockfile = data.get("lockfile")

    return DependencySpec(
        system=system,
        package_manager=package_manager,
        packages=packages,
        lockfile=lockfile,
    )


def parse_evals(data: dict | None) -> EvalConfig | None:
    """Parse the evals block from frontmatter."""
    if data is None:
        return None

    if not isinstance(data, dict):
        raise ValueError("'evals' must be a mapping.")

    agent = data.get("agent")
    if not agent or not isinstance(agent, str):
        raise ValueError("evals.agent is required and must be a string.")

    judge_model = data.get("judge_model")
    if not judge_model or not isinstance(judge_model, str):
        raise ValueError("evals.judge_model is required and must be a string.")

    return EvalConfig(agent=agent, judge_model=judge_model)


def parse_testing(data: dict | None) -> TestingConfig | None:
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

    # Validate runtime (supports both old driver field and new language field)
    if manifest.runtime:
        supported_languages = ("python",)
        if manifest.runtime.language not in supported_languages:
            errors.append(
                f"Unsupported runtime language '{manifest.runtime.language}'. "
                f"Supported: {', '.join(supported_languages)}"
            )

    return errors
