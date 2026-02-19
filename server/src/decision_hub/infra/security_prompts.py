"""Loader for security-sensitive LLM prompts.

Security prompts (gauntlet judges, topicality guard) are stored in a
YAML config file that is .gitignore'd to prevent leaking evasion hints
when the repo is open-sourced.
"""

from functools import lru_cache
from pathlib import Path

import yaml


@lru_cache
def load_security_prompts() -> dict[str, str]:
    """Load security-sensitive LLM prompts from YAML config.

    Raises FileNotFoundError if the config file is missing.
    No silent fallbacks — fail loudly so operators know to
    provide the file.
    """
    config_path = Path(__file__).parent / "security_prompts.yaml"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Security prompts config not found at {config_path}. "
            "Copy security_prompts.example.yaml or ask an admin for the production config."
        )
    with open(config_path) as f:
        prompts = yaml.safe_load(f)
    if not isinstance(prompts, dict):
        raise ValueError(f"security_prompts.yaml must be a YAML mapping, got {type(prompts)}")
    return prompts
