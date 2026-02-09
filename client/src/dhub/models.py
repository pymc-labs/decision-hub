"""Client-side domain models.

Shared models (SkillManifest, RuntimeConfig, etc.) are re-exported from
dhub_core — the single source of truth for SKILL.md data structures.
"""

from dhub_core.models import (  # noqa: F401
    AgentTestTarget,
    DependencySpec,
    EvalConfig,
    RuntimeConfig,
    SkillManifest,
    TestingConfig,
)
