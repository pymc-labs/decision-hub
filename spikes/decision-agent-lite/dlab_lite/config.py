"""
Configuration loading for decision packs (Docker-free version).

Differences from dlab:
- No docker_image_name required
- requirements.txt replaces Dockerfile
- agents/skills/tools live at top level (no opencode/ nesting)
"""

from pathlib import Path
from typing import Any

import yaml

REQUIRED_DIRS: list[str] = ["agents"]
REQUIRED_FILES: list[str] = ["config.yaml"]
CONFIG_KEYS: list[str] = ["name", "description", "default_model"]


def list_config_issues(config_dir: str) -> list[str]:
    """Check a decision-pack directory and return issues found."""
    issues: list[str] = []
    config_path: Path = Path(config_dir)

    if not config_path.exists():
        return [f"Directory does not exist: {config_dir}"]
    if not config_path.is_dir():
        return [f"Path is not a directory: {config_dir}"]

    for d in REQUIRED_DIRS:
        if not (config_path / d).is_dir():
            issues.append(f"Missing directory: {d}/")

    for f in REQUIRED_FILES:
        if not (config_path / f).is_file():
            issues.append(f"Missing file: {f}")

    return issues


def load_dpack_config(config_dir: str) -> dict[str, Any]:
    """Load and validate a decision-pack configuration."""
    config_path: Path = Path(config_dir).resolve()

    issues = list_config_issues(str(config_path))
    if issues:
        raise ValueError(f"Invalid decision-pack: {', '.join(issues)}")

    yaml_path = config_path / "config.yaml"
    with open(yaml_path) as f:
        config: dict[str, Any] = yaml.safe_load(f)

    missing = [k for k in CONFIG_KEYS if k not in config]
    if missing:
        raise ValueError(f"config.yaml missing keys: {missing}")

    config["config_dir"] = str(config_path)

    # Normalize hooks
    hooks = config.get("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
    for key in ("pre-run", "post-run"):
        val = hooks.get(key, [])
        if isinstance(val, str):
            hooks[key] = [val]
        elif not isinstance(val, list):
            hooks[key] = []
    config["hooks"] = hooks

    return config
