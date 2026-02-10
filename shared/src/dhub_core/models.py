"""Shared domain models as frozen dataclasses.

These models are the single source of truth for SKILL.md data structures,
used by both the client (dhub-cli) and server (decision-hub-server).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillManifest:
    """Parsed SKILL.md content."""

    name: str
    description: str
    license: str | None
    compatibility: str | None
    metadata: dict[str, str] | None
    allowed_tools: str | None
    runtime: "RuntimeConfig | None"
    evals: "EvalConfig | None"
    body: str
    testing: "TestingConfig | None" = None  # Legacy field for backward compatibility


@dataclass(frozen=True)
class DependencySpec:
    """Declared dependencies for a skill's runtime environment."""

    system: tuple[str, ...]
    package_manager: str
    packages: tuple[str, ...]
    lockfile: str | None


@dataclass(frozen=True)
class RuntimeConfig:
    """Soft contract: what the skill needs to run."""

    language: str
    entrypoint: str
    version_hint: str | None = None
    env: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    dependencies: DependencySpec | None = None
    repair_strategy: str = "attempt_install"


@dataclass(frozen=True)
class EvalConfig:
    """Eval configuration from SKILL.md frontmatter."""

    agent: str
    judge_model: str


@dataclass(frozen=True)
class AgentTestTarget:
    """Legacy testing target configuration."""

    name: str
    required_keys: tuple[str, ...]


@dataclass(frozen=True)
class TestingConfig:
    """Legacy testing configuration from SKILL.md frontmatter."""

    __test__ = False  # prevent pytest from trying to collect this dataclass
    cases: str
    agents: tuple[AgentTestTarget, ...]
