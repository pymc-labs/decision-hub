"""Verify the SKILL.md size guard added to manifest parsing.

Without an upper bound, a multi-megabyte body would be read into memory,
fed to PyYAML, and then stored in Postgres / sent into LLM prompts. The
size check rejects pathological files at the gate.
"""

import pytest

from dhub_core.manifest import _MAX_SKILL_MD_BYTES, parse_skill_md


def test_oversize_skill_md_is_rejected(tmp_path) -> None:
    path = tmp_path / "SKILL.md"
    # Build a file just over the limit. Content doesn't have to parse —
    # the size check runs before any parsing.
    path.write_text("x" * (_MAX_SKILL_MD_BYTES + 1))

    with pytest.raises(ValueError, match="too large"):
        parse_skill_md(path)


def test_normal_skill_md_is_still_accepted(tmp_path) -> None:
    """A small, valid manifest still parses (sanity guard against off-by-one)."""
    path = tmp_path / "SKILL.md"
    path.write_text('---\nname: my-skill\ndescription: "does a thing"\n---\n# My Skill\nBody goes here.\n')

    manifest = parse_skill_md(path)
    assert manifest.name == "my-skill"
