"""SKILL.md parser and validator — server extensions.

Core parsing and validation is delegated to dhub_core.manifest (the single
source of truth). This module re-exports that API and adds server-only
functions: extract_body, extract_description, parse_eval_cases_from_zip.
"""

import re

import yaml

from decision_hub.models import EvalCase
from dhub_core.manifest import (  # noqa: F401
    parse_skill_md,
    split_frontmatter,
    validate_manifest,
)


def extract_body(content: str) -> str:
    """Extract the body (system prompt) from SKILL.md content.

    Parses the frontmatter delimiters and returns the body text after
    the closing ---. Returns an empty string if parsing fails.
    """
    try:
        _, body = split_frontmatter(content)
        return body
    except ValueError:
        return ""


def extract_description(content: str) -> str:
    """Extract the description field from SKILL.md content.

    Parses the YAML frontmatter and returns the description string.
    Falls back to regex extraction when YAML parsing fails (e.g. when
    the description contains unquoted colons).
    Returns an empty string if the description is missing.
    """
    try:
        frontmatter_str, _ = split_frontmatter(content)
    except ValueError:
        return ""

    # Try standard YAML parsing first
    try:
        data = yaml.safe_load(frontmatter_str)
        if isinstance(data, dict):
            desc = data.get("description")
            return str(desc) if desc else ""
    except yaml.YAMLError:
        pass

    # Fallback: extract description line directly via regex.
    # Handles values with unquoted YAML-special characters like colons.
    match = re.search(r"^description:\s*(.+)$", frontmatter_str, re.MULTILINE)
    if match:
        return match.group(1).strip()

    return ""


def parse_eval_cases_from_zip(skill_zip: bytes) -> tuple[EvalCase, ...]:
    """Parse eval cases from evals/*.yaml files in a skill zip.

    Walks the zip archive looking for files matching evals/*.yaml,
    parses each one with YAML, and returns a tuple of EvalCase objects.

    Args:
        skill_zip: Raw bytes of a skill zip archive.

    Returns:
        Tuple of EvalCase instances.

    Raises:
        ValueError: If any eval case file is malformed.
    """
    import io
    import zipfile

    cases: list[EvalCase] = []

    with zipfile.ZipFile(io.BytesIO(skill_zip)) as zf:
        for name in zf.namelist():
            if name.startswith("evals/") and name.endswith(".yaml"):
                content = zf.read(name).decode("utf-8")
                data = yaml.safe_load(content)

                if not isinstance(data, dict):
                    raise ValueError(f"{name}: eval case must be a YAML mapping.")

                case_name = data.get("name")
                if not case_name or not isinstance(case_name, str):
                    raise ValueError(f"{name}: 'name' is required and must be a string.")

                description = data.get("description", "")
                if not isinstance(description, str):
                    raise ValueError(f"{name}: 'description' must be a string.")

                prompt = data.get("prompt")
                if not prompt or not isinstance(prompt, str):
                    raise ValueError(f"{name}: 'prompt' is required and must be a string.")

                judge_criteria = data.get("judge_criteria")
                if not judge_criteria or not isinstance(judge_criteria, str):
                    raise ValueError(f"{name}: 'judge_criteria' is required and must be a string.")

                cases.append(
                    EvalCase(
                        name=case_name,
                        description=description,
                        prompt=prompt,
                        judge_criteria=judge_criteria,
                    )
                )

    return tuple(cases)
