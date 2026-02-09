"""SKILL.md parser and validator.

Delegates to dhub_core.manifest — the single source of truth for
manifest parsing and validation. This module re-exports the public
API so existing client code continues to work unchanged.
"""

from dhub_core.manifest import (  # noqa: F401
    _NAME_PATTERN,
    parse_skill_md,
    validate_manifest,
)
