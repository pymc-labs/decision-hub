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
from dhub_core.plugin_manifest import (
    PluginHookRef,
    PluginManifest,
    PluginSkillRef,
    detect_plugin_platforms,
    parse_plugin_manifest,
)
from dhub_core.taxonomy import (
    ALL_SUBCATEGORIES,
    CATEGORY_TAXONOMY,
    DEFAULT_CATEGORY,
    SUBCATEGORY_TO_GROUP,
    SkillClassification,
)
from dhub_core.validation import (
    _SLUG_PATTERN,
    FIRST_VERSION,
    bump_version,
    parse_semver,
    validate_org_slug,
    validate_semver,
    validate_skill_name,
    validate_slug,
)
from dhub_core.ziputil import validate_zip_entries

__all__ = [
    "ALL_SUBCATEGORIES",
    "CATEGORY_TAXONOMY",
    "DEFAULT_CATEGORY",
    "FIRST_VERSION",
    "SUBCATEGORY_TO_GROUP",
    "_SLUG_PATTERN",
    "AgentTestTarget",
    "DependencySpec",
    "EvalConfig",
    "PluginHookRef",
    "PluginManifest",
    "PluginSkillRef",
    "RuntimeConfig",
    "SkillClassification",
    "SkillManifest",
    "TestingConfig",
    "bump_version",
    "detect_plugin_platforms",
    "parse_plugin_manifest",
    "parse_semver",
    "parse_skill_md",
    "validate_manifest",
    "validate_org_slug",
    "validate_semver",
    "validate_skill_name",
    "validate_slug",
    "validate_zip_entries",
]
