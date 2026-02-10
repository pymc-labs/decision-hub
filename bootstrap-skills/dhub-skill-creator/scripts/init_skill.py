"""Scaffold a new skill directory with minimal SKILL.md.

Creates a clean starting point — correct frontmatter + a heading.
No TODOs, no placeholder files, no meta-guidance.

Usage:
    python init_skill.py <skill-name> --path <dir> [--with-runtime] [--with-evals] [--description "..."]
"""

import argparse
import re
import sys
from pathlib import Path

_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")


def _build_frontmatter(
    name: str,
    description: str,
    with_runtime: bool,
    with_evals: bool,
) -> str:
    """Build YAML frontmatter string from options."""
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
    ]

    if with_runtime:
        lines.extend(
            [
                "runtime:",
                "  language: python",
                "  entrypoint: scripts/main.py",
            ]
        )

    if with_evals:
        lines.extend(
            [
                "evals:",
                "  agent: claude",
                "  judge_model: claude-sonnet-4-5-20250929",
            ]
        )

    lines.append("---")
    return "\n".join(lines)


def _build_skill_md(
    name: str,
    description: str,
    with_runtime: bool,
    with_evals: bool,
) -> str:
    """Build the complete SKILL.md content."""
    frontmatter = _build_frontmatter(name, description, with_runtime, with_evals)
    title = name.replace("-", " ").title()
    body = f"\n# {title}\n"
    return frontmatter + body


def init_skill(
    name: str,
    path: Path,
    description: str,
    with_runtime: bool = False,
    with_evals: bool = False,
) -> Path:
    """Create a skill directory with a minimal SKILL.md.

    Returns the path to the created skill directory.
    """
    skill_dir = path / name
    skill_dir.mkdir(parents=True, exist_ok=False)

    content = _build_skill_md(name, description, with_runtime, with_evals)
    (skill_dir / "SKILL.md").write_text(content)

    if with_runtime:
        (skill_dir / "scripts").mkdir()

    if with_evals:
        (skill_dir / "evals").mkdir()

    return skill_dir


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Scaffold a new skill directory.")
    parser.add_argument(
        "skill_name",
        help="Skill name (lowercase alphanumeric + hyphens, 1-64 chars)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("."),
        help="Parent directory for the new skill (default: current directory)",
    )
    parser.add_argument(
        "--description",
        default="A new skill.",
        help="Skill description for frontmatter",
    )
    parser.add_argument(
        "--with-runtime",
        action="store_true",
        help="Add runtime block and scripts/ directory",
    )
    parser.add_argument(
        "--with-evals",
        action="store_true",
        help="Add evals block and evals/ directory",
    )
    args = parser.parse_args()

    name = args.skill_name
    if not _NAME_PATTERN.match(name):
        print(
            f"Error: Invalid skill name '{name}'. "
            "Must be 1-64 chars, lowercase alphanumeric + hyphens, "
            "no leading/trailing hyphens.",
            file=sys.stderr,
        )
        return 1

    target = args.path.resolve()
    if not target.is_dir():
        print(f"Error: '{target}' is not a directory.", file=sys.stderr)
        return 1

    if (target / name).exists():
        print(f"Error: '{target / name}' already exists.", file=sys.stderr)
        return 1

    skill_dir = init_skill(
        name=name,
        path=target,
        description=args.description,
        with_runtime=args.with_runtime,
        with_evals=args.with_evals,
    )

    print(f"Created skill at: {skill_dir}")
    contents = sorted(p.relative_to(skill_dir) for p in skill_dir.rglob("*"))
    for item in contents:
        print(f"  {item}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
