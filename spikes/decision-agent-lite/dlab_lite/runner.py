"""
Agent runner for decision-agent-lite.

Uses the Claude Agent SDK for programmatic control over the coding agent,
replacing the raw subprocess call to `claude --print`.
"""

import anyio
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AgentDefinition,
    ResultMessage,
    AssistantMessage,
    SystemMessage,
    TextBlock,
)


def build_system_prompt(work_dir: str, agent_name: str = "orchestrator") -> str:
    """
    Build a complete system prompt from decision pack components.

    Concatenates: agent prompt + all referenced skills.
    """
    work_path = Path(work_dir)
    agents_dir = work_path / ".agents"
    skills_dir = work_path / ".skills"

    # Load agent prompt
    agent_file = agents_dir / f"{agent_name}.md"
    if not agent_file.exists():
        raise ValueError(f"Agent not found: {agent_name}")

    agent_content = agent_file.read_text()

    # Parse frontmatter to find referenced skills
    skills_to_load = []
    if agent_content.startswith("---"):
        _, frontmatter, body = agent_content.split("---", 2)
        for line in frontmatter.strip().split("\n"):
            line = line.strip()
            if line.startswith("- ") and skills_dir.exists():
                skill_name = line[2:].strip()
                skill_file = skills_dir / f"{skill_name}.md"
                if skill_file.exists():
                    skills_to_load.append(skill_file)
        agent_content = body.strip()

    # Build full prompt
    parts = [agent_content]

    for skill_file in skills_to_load:
        parts.append(f"\n\n---\n## Skill: {skill_file.stem}\n\n{skill_file.read_text()}")

    return "\n".join(parts)


def _load_parallel_agents(work_dir: str) -> dict[str, AgentDefinition]:
    """Load parallel agent definitions from .parallel_agents/ YAML configs."""
    import yaml

    work_path = Path(work_dir)
    pa_dir = work_path / ".parallel_agents"
    agents = {}

    if not pa_dir.exists():
        return agents

    for config_file in pa_dir.glob("*.yaml"):
        with open(config_file) as f:
            pa_config = yaml.safe_load(f)

        agent_name = config_file.stem
        description = pa_config.get("description", f"Sub-agent: {agent_name}")

        # Build the sub-agent's prompt from its agent file + skills
        try:
            sub_prompt = build_system_prompt(work_dir, agent_name)
        except ValueError:
            # No matching agent file — use a generic prompt
            sub_prompt = f"You are a sub-agent running the {agent_name} workflow."

        agents[agent_name] = AgentDefinition(
            description=description,
            prompt=sub_prompt,
            tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        )

    return agents


async def _run_agent_async(
    work_dir: str,
    prompt: str,
    model: str,
    agent_name: str = "orchestrator",
    venv_python: str | None = None,
) -> int:
    """Async implementation of agent runner using Claude Agent SDK."""
    system_prompt = build_system_prompt(work_dir, agent_name)

    # Build the full prompt with context
    full_prompt = f"""{prompt}

Working directory: {work_dir}
Data directory: {work_dir}/data/
Figures directory: {work_dir}/figures/
"""

    if venv_python:
        full_prompt += f"\nPython interpreter: {venv_python}\n"

    # Load parallel agent definitions if present
    subagents = _load_parallel_agents(work_dir)

    # Determine allowed tools
    allowed_tools = ["Read", "Write", "Edit", "Bash", "Glob", "Grep"]
    if subagents:
        allowed_tools.append("Agent")

    # Set up environment — add lib/ to PYTHONPATH if it exists
    env = {}
    lib_dir = Path(work_dir) / "lib"
    if lib_dir.exists():
        env["PYTHONPATH"] = str(lib_dir)

    options = ClaudeAgentOptions(
        cwd=work_dir,
        model=model,
        system_prompt=system_prompt,
        allowed_tools=allowed_tools,
        permission_mode="bypassPermissions",
        max_turns=50,
        env=env,
    )

    if subagents:
        options.agents = subagents

    print(f"\n  Running agent ({agent_name}) with model {model}...")
    print(f"  Work directory: {work_dir}")
    print(f"  Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")
    if subagents:
        print(f"  Sub-agents: {', '.join(subagents.keys())}")
    print()

    try:
        async for message in query(prompt=full_prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        print(block.text)
            elif isinstance(message, ResultMessage):
                print(f"\n  Agent finished (stop_reason: {message.stop_reason})")
                return 0
    except Exception as e:
        print(f"\n  Agent error: {e}")
        return 1

    return 0


def run_agent(
    work_dir: str,
    prompt: str,
    model: str,
    agent_name: str = "orchestrator",
    venv_python: str | None = None,
) -> int:
    """
    Run the coding agent on a prepared work directory.

    Uses the Claude Agent SDK for streaming output, programmatic tool control,
    and sub-agent support.

    Parameters
    ----------
    work_dir : str
        Path to the session work directory.
    prompt : str
        User prompt for the agent.
    model : str
        Model to use (e.g., "claude-sonnet-4-6").
    agent_name : str
        Which agent to use as primary (default: "orchestrator").
    venv_python : str | None
        Path to venv python for running scripts.

    Returns
    -------
    int
        Exit code (0 = success).
    """
    return anyio.run(
        _run_agent_async, work_dir, prompt, model, agent_name, venv_python
    )
