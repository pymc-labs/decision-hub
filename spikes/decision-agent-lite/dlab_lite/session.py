"""
Session management for decision-agent-lite.

Creates work directories, copies data and agent configs,
sets up Python venvs (replaces Docker).
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


SESSION_DIR_PREFIX: str = "dlab-analysis-"
STATE_FILE: str = ".state.json"


def get_next_sequence_number(base_dir: str) -> int:
    """Find the next available session sequence number."""
    base_path = Path(base_dir)
    if not base_path.exists():
        return 1

    pattern = re.compile(rf"^{re.escape(SESSION_DIR_PREFIX)}(\d+)$")
    max_seq = 0

    for item in base_path.iterdir():
        if item.is_dir():
            match = pattern.match(item.name)
            if match:
                max_seq = max(max_seq, int(match.group(1)))

    return max_seq + 1


def setup_venv(config: dict[str, Any], work_dir: str) -> str | None:
    """
    Create a Python venv and install requirements if specified.

    Returns the path to the venv's python, or None if no requirements.
    """
    config_dir = Path(config["config_dir"])
    req_file = config.get("requirements")

    if not req_file:
        # Check for requirements.txt in the decision pack
        if (config_dir / "requirements.txt").exists():
            req_file = "requirements.txt"
        else:
            return None

    req_path = config_dir / req_file
    if not req_path.exists():
        return None

    venv_path = Path(work_dir) / ".venv"
    print(f"  Creating venv at {venv_path}...")

    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_path)],
        check=True,
        capture_output=True,
    )

    pip = str(venv_path / "bin" / "pip")
    print(f"  Installing dependencies from {req_file}...")

    result = subprocess.run(
        [pip, "install", "-r", str(req_path)],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"  Warning: pip install failed: {result.stderr[:500]}")

    return str(venv_path / "bin" / "python")


def copy_data(data_paths: list[str], work_dir: str) -> None:
    """Copy data files/directories into the work directory."""
    dest = Path(work_dir) / "data"
    dest.mkdir(parents=True, exist_ok=True)

    for p in data_paths:
        src = Path(p)
        if not src.exists():
            raise ValueError(f"Data path does not exist: {p}")
        if src.is_dir():
            shutil.copytree(src, dest / src.name)
        else:
            shutil.copy2(src, dest / src.name)


def setup_agent_config(config_dir: str, work_dir: str) -> None:
    """
    Copy agent configs into the work directory.

    In dlab, this goes into .opencode/. Here we copy to .agents/
    which the runner reads to build the system prompt.
    """
    config_path = Path(config_dir)
    work_path = Path(work_dir)

    # Copy agents
    agents_src = config_path / "agents"
    if agents_src.exists():
        shutil.copytree(agents_src, work_path / ".agents")

    # Copy skills
    skills_src = config_path / "skills"
    if skills_src.exists():
        shutil.copytree(skills_src, work_path / ".skills")

    # Copy tools
    tools_src = config_path / "tools"
    if tools_src.exists():
        shutil.copytree(tools_src, work_path / ".tools")

    # Copy parallel agent configs
    pa_src = config_path / "parallel_agents"
    if pa_src.exists():
        shutil.copytree(pa_src, work_path / ".parallel_agents")

    # Copy lib/ (domain-specific Python libraries like mmm_lib)
    lib_src = config_path / "lib"
    if lib_src.exists():
        shutil.copytree(lib_src, work_path / "lib")


def save_state(work_dir: str, state: dict[str, Any]) -> None:
    """Save session state to .state.json."""
    with open(Path(work_dir) / STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def create_session(
    config: dict[str, Any],
    data_paths: list[str] | None,
    work_dir: str | None = None,
    base_dir: str = ".",
) -> dict[str, Any]:
    """Create a new analysis session."""
    if work_dir is None:
        seq = get_next_sequence_number(base_dir)
        work_dir = str(Path(base_dir) / f"{SESSION_DIR_PREFIX}{seq:03d}")

    work_path = Path(work_dir).resolve()
    if work_path.exists():
        raise ValueError(f"Work directory already exists: {work_dir}")

    work_path.mkdir(parents=True)
    (work_path / "figures").mkdir()

    # Initialize git repo (agents expect it)
    subprocess.run(
        ["git", "init"],
        cwd=work_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Copy data
    if data_paths:
        copy_data(data_paths, str(work_path))

    # Copy agent configs
    setup_agent_config(config["config_dir"], str(work_path))

    state = {
        "work_dir": str(work_path),
        "config_dir": config["config_dir"],
        "dpack_name": config["name"],
        "status": "created",
    }
    save_state(str(work_path), state)

    return state
