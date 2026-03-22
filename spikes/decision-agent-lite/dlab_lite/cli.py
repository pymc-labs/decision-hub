"""
CLI for decision-agent-lite.

Simplified version of dlab CLI without Docker dependency.
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from dlab_lite.config import load_dpack_config
from dlab_lite.session import create_session, setup_venv
from dlab_lite.runner import run_agent


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dlab-lite",
        description="Run decision packs without Docker",
    )

    subparsers = parser.add_subparsers(dest="command")

    # Run mode (default)
    parser.add_argument("--dpack", metavar="PATH", help="Path to decision-pack directory")
    parser.add_argument("--data", nargs="+", metavar="PATH", help="Data files or directories")
    parser.add_argument("--model", metavar="MODEL", help="Model override")
    parser.add_argument("--prompt", metavar="TEXT", help="Prompt text")
    parser.add_argument("--prompt-file", metavar="PATH", help="Path to prompt file")
    parser.add_argument("--work-dir", metavar="PATH", help="Explicit work directory")
    parser.add_argument("--skip-venv", action="store_true", help="Skip venv creation")
    parser.add_argument("--dry-run", action="store_true", help="Set up session but don't run agent")

    # Create decision-pack
    create_parser_cmd = subparsers.add_parser("create-dpack", help="Create a new decision pack")
    create_parser_cmd.add_argument("name", help="Decision pack name")
    create_parser_cmd.add_argument("--output-dir", default=".", help="Output directory")

    # Info
    info_parser = subparsers.add_parser("info", help="Show decision pack info")
    info_parser.add_argument("dpack", help="Path to decision-pack directory")

    return parser


def cmd_run(args: argparse.Namespace) -> int:
    """Run a decision pack."""
    if not args.dpack:
        print("Error: --dpack is required", file=sys.stderr)
        return 1

    try:
        config = load_dpack_config(args.dpack)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    requires_data = config.get("requires_data", True)
    requires_prompt = config.get("requires_prompt", True)

    if requires_data and not args.data:
        print("Error: --data is required for this decision pack", file=sys.stderr)
        return 1

    if requires_prompt and not args.prompt and not args.prompt_file:
        print("Error: --prompt or --prompt-file is required", file=sys.stderr)
        return 1

    prompt = ""
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text()
    elif args.prompt:
        prompt = args.prompt

    model = args.model or config["default_model"]

    # Create session
    print(f"dlab-lite · {config['name']} · {model}")
    print()

    try:
        state = create_session(config, args.data, work_dir=args.work_dir)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    work_dir = state["work_dir"]
    print(f"  Session: {work_dir}")

    # Set up venv (replaces Docker image build)
    venv_python = None
    if not args.skip_venv:
        venv_python = setup_venv(config, work_dir)
        if venv_python:
            print(f"  Venv ready: {venv_python}")
        else:
            print("  No requirements.txt — skipping venv")

    if args.dry_run:
        print("\n  Dry run — session prepared but agent not started.")
        print(f"  To run manually: cd {work_dir} && claude")
        return 0

    # Run the agent
    exit_code = run_agent(work_dir, prompt, model, venv_python=venv_python)

    if exit_code == 0:
        print(f"\n  Done. Results in: {work_dir}")
    else:
        print(f"\n  Agent exited with code {exit_code}")

    return exit_code


def cmd_create_dpack(args: argparse.Namespace) -> int:
    """Scaffold a new decision pack."""
    name = args.name
    output = Path(args.output_dir) / name

    if output.exists():
        print(f"Error: {output} already exists", file=sys.stderr)
        return 1

    output.mkdir(parents=True)
    (output / "agents").mkdir()
    (output / "skills").mkdir()
    (output / "tools").mkdir()

    # config.yaml
    (output / "config.yaml").write_text(f"""name: {name}
description: [describe what this decision pack does]
default_model: anthropic/claude-sonnet-4-5
requires_data: true
requires_prompt: true
""")

    # requirements.txt
    (output / "requirements.txt").write_text("""numpy>=1.24
pandas>=2.0
matplotlib>=3.7
""")

    # Orchestrator template
    (output / "agents" / "orchestrator.md").write_text(f"""---
description: Orchestrates {name} workflow
mode: primary
tools:
  read: true
  edit: true
  bash: true
skills: []
---

# {name} — Orchestrator

You are a data scientist running the {name} analysis workflow.

## Your Workflow

### Step 1: Data Exploration
- Load data from `/workspace/data/`
- Write `data_summary.md`

### Step 2: Analysis
- [Define your analysis steps here]

### Step 3: Report
- Write `report.md` with results
- Save figures to `/workspace/figures/`
""")

    print(f"Created decision pack: {output}")
    print(f"  config.yaml        — edit name, description, model")
    print(f"  requirements.txt   — add Python dependencies")
    print(f"  agents/orchestrator.md — define the analysis workflow")
    print(f"  skills/            — add domain knowledge files")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    """Show decision pack information."""
    try:
        config = load_dpack_config(args.dpack)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    config_path = Path(config["config_dir"])

    print(f"Name:        {config['name']}")
    print(f"Description: {config['description']}")
    print(f"Model:       {config['default_model']}")
    print(f"Path:        {config_path}")
    print()

    # List agents
    agents_dir = config_path / "agents"
    if agents_dir.exists():
        agents = sorted(agents_dir.glob("*.md"))
        print(f"Agents ({len(agents)}):")
        for a in agents:
            print(f"  - {a.stem}")

    # List skills
    skills_dir = config_path / "skills"
    if skills_dir.exists():
        skills = sorted(skills_dir.glob("*.md"))
        print(f"Skills ({len(skills)}):")
        for s in skills:
            print(f"  - {s.stem}")

    # Requirements
    req = config_path / "requirements.txt"
    if req.exists():
        deps = [l.strip() for l in req.read_text().splitlines() if l.strip() and not l.startswith("#")]
        print(f"Dependencies ({len(deps)}): {', '.join(deps)}")

    return 0


def main() -> None:
    parser = create_parser()
    args = parser.parse_args()

    if args.command == "create-dpack":
        exit_code = cmd_create_dpack(args)
    elif args.command == "info":
        exit_code = cmd_info(args)
    elif args.dpack or args.data or args.prompt:
        exit_code = cmd_run(args)
    else:
        parser.print_help()
        exit_code = 0

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
