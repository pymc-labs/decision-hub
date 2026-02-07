"""Validate and package a skill directory into a distributable zip.

Runs full validation first (fails fast on errors), then creates a clean
zip excluding common junk files.

Usage:
    python package_skill.py <skill-directory> [--output-dir <dir>]
"""

import sys
import zipfile
from pathlib import Path

from validate_skill import print_report, validate_skill

_EXCLUDE_PATTERNS = {
    "__pycache__",
    ".git",
    ".DS_Store",
    ".env",
}

_EXCLUDE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".egg-info",
}


def _should_exclude(path: Path) -> bool:
    """Check if a file or directory should be excluded from the zip."""
    for part in path.parts:
        if part in _EXCLUDE_PATTERNS:
            return True
        if any(part.endswith(suffix) for suffix in _EXCLUDE_SUFFIXES):
            return True
        if part.startswith(".env"):
            return True
    return False


def package_skill(skill_dir: Path, output_dir: Path) -> Path:
    """Create a zip archive of the skill directory.

    Validates the skill first (raises SystemExit on errors).
    Returns the path to the created zip file.
    """
    is_valid, errors, warnings = validate_skill(skill_dir)
    print_report(skill_dir, errors, warnings, strict=False)

    if not is_valid:
        print("\nPackaging aborted due to validation errors.", file=sys.stderr)
        sys.exit(1)

    skill_name = skill_dir.name
    output_path = output_dir / f"{skill_name}.zip"
    file_count = 0
    total_size = 0

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(skill_dir.rglob("*")):
            if not file_path.is_file():
                continue

            relative = file_path.relative_to(skill_dir)
            if _should_exclude(relative):
                continue

            zf.write(file_path, str(relative))
            file_count += 1
            total_size += file_path.stat().st_size

    print(f"\nPackaged: {output_path}")
    print(f"  Files: {file_count}")
    print(f"  Size:  {total_size:,} bytes (uncompressed)")

    return output_path


def main() -> int:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate and package a skill into a zip archive."
    )
    parser.add_argument("skill_directory", type=Path, help="Path to the skill directory")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for the zip (default: parent of skill directory)",
    )
    args = parser.parse_args()

    skill_path = args.skill_directory.resolve()
    if not skill_path.is_dir():
        print(f"Error: '{skill_path}' is not a directory.", file=sys.stderr)
        return 1

    output_dir = (args.output_dir or skill_path.parent).resolve()
    if not output_dir.is_dir():
        print(f"Error: Output directory '{output_dir}' does not exist.", file=sys.stderr)
        return 1

    package_skill(skill_path, output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
