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
from dhub_core.taxonomy import (
    ALL_SUBCATEGORIES,
    CATEGORY_TAXONOMY,
    DEFAULT_CATEGORY,
    SUBCATEGORY_TO_GROUP,
    SkillClassification,
)
from dhub_core.validation import FIRST_VERSION, validate_semver, validate_skill_name

__all__ = [
    "ALL_SUBCATEGORIES",
    "CATEGORY_TAXONOMY",
    "DEFAULT_CATEGORY",
    "FIRST_VERSION",
    "SUBCATEGORY_TO_GROUP",
    "AgentTestTarget",
    "DependencySpec",
    "EvalConfig",
    "RuntimeConfig",
    "SkillClassification",
    "SkillManifest",
    "TestingConfig",
    "parse_skill_md",
    "validate_manifest",
    "validate_semver",
    "validate_skill_name",
]
