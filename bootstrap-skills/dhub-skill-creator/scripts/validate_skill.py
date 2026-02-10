"""Validate a skill directory against the Decision Hub SKILL.md format.

Runs 15+ checks aligned with the server's skill_manifest.py parser.
Pure functions with colored terminal output.

Usage:
    python validate_skill.py <skill-directory> [--strict]

Exit codes: 0 = valid, 1 = errors found, 2 = warnings promoted by --strict.
"""

import re
import sys
from pathlib import Path

import yaml

_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$")
_ENV_VAR_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PLACEHOLDER_PATTERNS = (
    re.compile(r"\bTODO\b", re.IGNORECASE),
    re.compile(r"\bplaceholder\b", re.IGNORECASE),
    re.compile(r"\bFIXME\b", re.IGNORECASE),
    re.compile(r"\bXXX\b"),
)


def _split_frontmatter(content: str) -> tuple[str, str]:
    """Split SKILL.md content into frontmatter string and body."""
    lines = content.split("\n")

    start = 0
    while start < len(lines) and lines[start].strip() == "":
        start += 1

    if start >= len(lines) or lines[start].strip() != "---":
        return "", ""

    close = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "---":
            close = i
            break

    if close is None:
        return "", ""

    frontmatter_str = "\n".join(lines[start + 1 : close])
    body = "\n".join(lines[close + 1 :]).strip()
    return frontmatter_str, body


def _parse_yaml_with_fallback(frontmatter_str: str) -> dict | None:
    """Parse YAML frontmatter with colon fallback (mirrors server logic)."""
    try:
        data = yaml.safe_load(frontmatter_str)
        if isinstance(data, dict):
            return data
        return None
    except yaml.YAMLError:
        pass

    # Fallback: quote top-level scalar fields with unquoted colons
    lines = frontmatter_str.split("\n")
    patched: list[str] = []
    for line in lines:
        m = re.match(r"^(name|description):\s*(.+)$", line)
        if m and ":" in m.group(2):
            patched.append(f'{m.group(1)}: "{m.group(2)}"')
        else:
            patched.append(line)

    try:
        data = yaml.safe_load("\n".join(patched))
        if isinstance(data, dict):
            return data
    except yaml.YAMLError:
        pass

    return None


def _has_placeholder(text: str) -> bool:
    """Check if text contains TODO/placeholder/FIXME markers."""
    return any(p.search(text) for p in _PLACEHOLDER_PATTERNS)


def validate_skill(path: Path, strict: bool = False) -> tuple[bool, list[str], list[str]]:
    """Validate a skill directory.

    Returns (is_valid, errors, warnings). When strict=True, warnings
    are promoted to errors and is_valid reflects that.
    """
    errors: list[str] = []
    warnings: list[str] = []
    skill_dir = Path(path)

    # --- Check: SKILL.md exists ---
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        errors.append("SKILL.md not found in skill directory.")
        return (False, errors, warnings)

    content = skill_md.read_text()

    # --- Check: valid YAML frontmatter (--- delimiters) ---
    frontmatter_str, body = _split_frontmatter(content)
    if not frontmatter_str:
        errors.append("Invalid or missing YAML frontmatter. SKILL.md must start with --- and have a closing ---.")
        return (False, errors, warnings)

    data = _parse_yaml_with_fallback(frontmatter_str)
    if data is None:
        errors.append("Frontmatter is not valid YAML.")
        return (False, errors, warnings)

    # --- Check: body is non-empty ---
    if not body:
        errors.append("Body (system prompt) must not be empty.")

    # --- Check: name present and valid ---
    name = data.get("name")
    if not name or not isinstance(name, str):
        errors.append("Required field 'name' is missing.")
    elif not _NAME_PATTERN.match(name):
        errors.append(
            f"Invalid name '{name}': must be 1-64 chars, lowercase alphanumeric + hyphens, no leading/trailing hyphens."
        )
    else:
        # --- Check: name matches directory name ---
        if name != skill_dir.name:
            errors.append(f"Skill name '{name}' does not match directory name '{skill_dir.name}'.")

    # --- Check: no placeholder text in name ---
    if isinstance(name, str) and _has_placeholder(name):
        errors.append(f"Name '{name}' contains TODO/placeholder text.")

    # --- Check: description present and valid length ---
    description = data.get("description")
    if not description or not isinstance(description, str):
        errors.append("Required field 'description' is missing.")
    else:
        if len(description) > 1024:
            errors.append(f"Description too long ({len(description)} chars). Max 1024.")
        # --- Check: no placeholder text in description ---
        if _has_placeholder(description):
            errors.append("Description contains TODO/placeholder text.")
        # --- Warning: very short description ---
        if len(description) < 20:
            warnings.append(
                f"Description is very short ({len(description)} chars). Consider making it more descriptive."
            )

    # --- Warning: very short body ---
    if body and len(body) < 100:
        warnings.append(f"Body is very short ({len(body)} chars). Consider adding more detail to the system prompt.")

    # --- Validate runtime block ---
    runtime = data.get("runtime")
    if isinstance(runtime, dict):
        language = runtime.get("language")
        if not language or language != "python":
            errors.append(f"runtime.language must be 'python'. Got: '{language}'.")

        entrypoint = runtime.get("entrypoint")
        if not entrypoint or not isinstance(entrypoint, str):
            errors.append("runtime.entrypoint is required and must be a string.")
        else:
            # --- Check: entrypoint file exists ---
            entrypoint_path = skill_dir / entrypoint
            if not entrypoint_path.exists():
                errors.append(f"runtime.entrypoint '{entrypoint}' does not exist (expected at {entrypoint_path}).")

        # --- Warning: env var names ---
        env_items = runtime.get("env", [])
        if isinstance(env_items, list):
            for item in env_items:
                if isinstance(item, str) and not _ENV_VAR_PATTERN.match(item):
                    warnings.append(
                        f"runtime.env item '{item}' doesn't look like an "
                        "environment variable name (expected UPPER_SNAKE_CASE)."
                    )

    # --- Validate evals block ---
    evals = data.get("evals")
    if isinstance(evals, dict):
        agent = evals.get("agent")
        if not agent or not isinstance(agent, str):
            errors.append("evals.agent is required and must be a string.")

        judge_model = evals.get("judge_model")
        if not judge_model or not isinstance(judge_model, str):
            errors.append("evals.judge_model is required and must be a string.")

        # --- Warning: at least one eval case file exists ---
        evals_dir = skill_dir / "evals"
        eval_files = list(evals_dir.glob("*.yaml")) if evals_dir.is_dir() else []
        if not eval_files:
            warnings.append(
                "evals block defined but no evals/*.yaml files found. Add eval case files or remove the evals block."
            )

        # --- Validate each eval case YAML ---
        eval_names: list[str] = []
        for eval_file in eval_files:
            try:
                case_data = yaml.safe_load(eval_file.read_text())
            except yaml.YAMLError as e:
                errors.append(f"{eval_file.name}: invalid YAML — {e}")
                continue

            if not isinstance(case_data, dict):
                errors.append(f"{eval_file.name}: eval case must be a YAML mapping.")
                continue

            case_name = case_data.get("name")
            if not case_name or not isinstance(case_name, str):
                errors.append(f"{eval_file.name}: 'name' is required.")
            else:
                eval_names.append(case_name)

            if not case_data.get("prompt"):
                errors.append(f"{eval_file.name}: 'prompt' is required.")

            if not case_data.get("judge_criteria"):
                errors.append(f"{eval_file.name}: 'judge_criteria' is required.")

        # --- Check: eval names are unique ---
        seen: set[str] = set()
        for en in eval_names:
            if en in seen:
                errors.append(f"Duplicate eval case name: '{en}'.")
            seen.add(en)

    # Determine validity
    if strict:
        all_issues = errors + warnings
        is_valid = len(all_issues) == 0
    else:
        is_valid = len(errors) == 0

    return (is_valid, errors, warnings)


def _color(text: str, code: str) -> str:
    """Wrap text in ANSI color codes."""
    return f"\033[{code}m{text}\033[0m"


def print_report(skill_path: Path, errors: list[str], warnings: list[str], strict: bool) -> None:
    """Print a colored validation report to stdout."""
    print(f"\nValidating: {skill_path}\n")

    if not errors and not warnings:
        print(_color("  PASS  All checks passed.", "32"))
        return

    for err in errors:
        print(f"  {_color('ERROR', '31')}  {err}")

    for warn in warnings:
        label = "ERROR" if strict else "WARN "
        color = "31" if strict else "33"
        print(f"  {_color(label, color)}  {warn}")

    total = len(errors) + (len(warnings) if strict else 0)
    if total > 0:
        print(f"\n  {_color(f'{total} issue(s) found.', '31')}")
    else:
        print(f"\n  {_color('PASS', '32')}  No errors. {len(warnings)} warning(s).")


def main() -> int:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate a skill directory against the SKILL.md format.")
    parser.add_argument("skill_directory", type=Path, help="Path to the skill directory")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Promote warnings to errors",
    )
    args = parser.parse_args()

    skill_path = args.skill_directory.resolve()
    if not skill_path.is_dir():
        print(f"Error: '{skill_path}' is not a directory.", file=sys.stderr)
        return 1

    is_valid, errors, warnings = validate_skill(skill_path, strict=args.strict)
    print_report(skill_path, errors, warnings, strict=args.strict)

    if not is_valid:
        return 2 if (not errors and args.strict) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
