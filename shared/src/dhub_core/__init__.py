"""Shared domain models and manifest parsing for Decision Hub.

This package is the single source of truth for SKILL.md parsing,
validation, and the data models shared between client and server.
"""

from dhub_core.manifest import parse_skill_md, validate_manifest
from dhub_core.models import (
    AgentTestTarget,
    DependencySpec,
    EvalConfig,
    RuntimeConfig,
    SkillManifest,
    TestingConfig,
)
from dhub_core.validation import FIRST_VERSION, validate_semver, validate_skill_name

__all__ = [
    "FIRST_VERSION",
    "AgentTestTarget",
    "DependencySpec",
    "EvalConfig",
    "RuntimeConfig",
    "SkillManifest",
    "TestingConfig",
    "parse_skill_md",
    "validate_manifest",
    "validate_semver",
    "validate_skill_name",
]
