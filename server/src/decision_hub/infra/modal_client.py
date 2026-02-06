"""Modal sandbox management for agent-aware skill evaluations.

Provides functions to build agent-specific container images and run
skill tests inside Modal sandboxes with injected API keys.
"""

from dataclasses import dataclass

from decision_hub.models import AgentSandboxConfig


# ---------------------------------------------------------------------------
# Agent configurations
# ---------------------------------------------------------------------------

AGENT_CONFIGS: dict[str, AgentSandboxConfig] = {
    "claude": AgentSandboxConfig(
        npm_package="@anthropic-ai/claude-code",
        skills_path=".claude/skills",
        run_cmd=("claude", "--dangerously-skip-permissions"),
        key_env_var="ANTHROPIC_API_KEY",
        extra_env={"NON_INTERACTIVE_MODE": "true"},
    ),
    "codex": AgentSandboxConfig(
        npm_package="codex",
        skills_path=".codex/skills",
        run_cmd=("codex", "run", "--json", "--ask-for-approval", "never"),
        key_env_var="CODEX_API_KEY",
        extra_env={},
    ),
    "gemini": AgentSandboxConfig(
        npm_package="@google/gemini-cli",
        skills_path=".gemini/skills",
        run_cmd=("gemini", "--prompt"),
        key_env_var="GEMINI_API_KEY",
        extra_env={},
    ),
}


def get_agent_config(agent_name: str) -> AgentSandboxConfig:
    """Look up the sandbox configuration for a named agent.

    Raises:
        ValueError: If the agent name is not recognized.
    """
    config = AGENT_CONFIGS.get(agent_name)
    if config is None:
        supported = ", ".join(sorted(AGENT_CONFIGS))
        raise ValueError(
            f"Unknown agent '{agent_name}'. Supported agents: {supported}"
        )
    return config


# ---------------------------------------------------------------------------
# Modal image building
# ---------------------------------------------------------------------------


def build_eval_image(config: AgentSandboxConfig):
    """Build a Modal image for a specific agent.

    The image is based on node:20-slim with the agent's NPM package
    installed globally, plus uv for Python dependency management.

    Returns:
        A modal.Image configured for the agent.
    """
    import modal

    return (
        modal.Image.from_registry("node:20-slim")
        .apt_install("python3", "python3-pip", "curl")
        .run_commands(
            f"npm install -g {config.npm_package}",
            "pip install uv --break-system-packages",
        )
    )


# ---------------------------------------------------------------------------
# Sandbox helpers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SandboxResult:
    """Result from running test cases in a sandbox."""
    outputs: tuple[tuple[str, int], ...]  # (stdout, exit_code) per case


def build_agent_run_command(
    agent_config: AgentSandboxConfig,
    prompt: str,
) -> list[str]:
    """Build the command to invoke an agent with a test prompt."""
    return list(agent_config.run_cmd) + [prompt]


def _run_in_sandbox(sb, *args: str):
    """Run a command inside a Modal sandbox and return (stdout, exit_code).

    Uses Modal's Sandbox API to run arbitrary commands
    inside the sandboxed environment.
    """
    # Modal SDK renamed process() -> exec() in recent versions
    run_fn = getattr(sb, "exec", None) or sb.process
    proc = run_fn(*args)
    proc.wait()
    return proc.stdout.read(), proc.returncode


def run_skill_tests_in_sandbox(
    skill_zip: bytes,
    test_prompts: tuple[str, ...],
    agent_config: AgentSandboxConfig,
    agent_env_vars: dict[str, str],
    org_slug: str,
    skill_name: str,
) -> SandboxResult:
    """Run skill test cases inside a Modal sandbox.

    Steps:
    1. Build an agent-specific image
    2. Create a Modal sandbox with the image and env vars
    3. Upload and extract the skill zip to the agent's skills path
    4. For each test prompt: invoke the agent CLI and capture output
    5. Return collected outputs and exit codes

    Args:
        skill_zip: Raw bytes of the skill zip archive.
        test_prompts: Tuple of prompts to run as test cases.
        agent_config: Configuration for the target agent.
        agent_env_vars: Decrypted environment variables (API keys).
        org_slug: Organisation slug for skill path placement.
        skill_name: Skill name for skill path placement.

    Returns:
        SandboxResult with outputs for each test case.
    """
    import base64
    import modal

    image = build_eval_image(agent_config)

    # Merge agent-specific extra env with the user's decrypted keys
    env = {**agent_config.extra_env, **agent_env_vars}

    app = modal.App.lookup("decision-hub-eval", create_if_missing=True)
    skill_path = f"/root/{agent_config.skills_path}/{org_slug}/{skill_name}"

    outputs: list[tuple[str, int]] = []

    with modal.enable_output():
        sb = modal.Sandbox.create(
            image=image,
            secrets=[modal.Secret.from_dict(env)],
            app=app,
        )

        # Set up skill directory
        _run_in_sandbox(sb, "mkdir", "-p", skill_path)

        # Transfer and extract skill zip via base64 + Python zipfile
        b64_zip = base64.b64encode(skill_zip).decode()
        _run_in_sandbox(
            sb,
            "python3", "-c",
            f"import base64,zipfile,io; "
            f"data=base64.b64decode('{b64_zip}'); "
            f"zipfile.ZipFile(io.BytesIO(data)).extractall('{skill_path}')",
        )

        # Install Python deps if pyproject.toml exists
        _run_in_sandbox(
            sb,
            "python3", "-c",
            f"import os,subprocess; "
            f"os.path.isfile('{skill_path}/pyproject.toml') and "
            f"subprocess.run(['uv','sync','--directory','{skill_path}'])",
        )

        # Run each test prompt through the agent
        for prompt in test_prompts:
            cmd = build_agent_run_command(agent_config, prompt)
            stdout, exit_code = _run_in_sandbox(sb, *cmd)
            outputs.append((stdout, exit_code))

        sb.terminate()

    return SandboxResult(outputs=tuple(outputs))


def _create_skill_sandbox(
    skill_zip: bytes,
    agent_config: AgentSandboxConfig,
    agent_env_vars: dict[str, str],
    org_slug: str,
    skill_name: str,
):
    """Create and prepare a Modal sandbox with a skill installed.

    Returns:
        A tuple of (sandbox, skill_path) ready for running commands.
    """
    import base64
    import modal

    image = build_eval_image(agent_config)

    # Merge agent-specific extra env with the user's decrypted keys
    env = {**agent_config.extra_env, **agent_env_vars}

    app = modal.App.lookup("decision-hub-eval", create_if_missing=True)
    skill_path = f"/root/{agent_config.skills_path}/{org_slug}/{skill_name}"

    with modal.enable_output():
        sb = modal.Sandbox.create(
            image=image,
            secrets=[modal.Secret.from_dict(env)],
            app=app,
        )

        # Set up skill directory
        _run_in_sandbox(sb, "mkdir", "-p", skill_path)

        # Transfer and extract skill zip via base64 + Python zipfile
        b64_zip = base64.b64encode(skill_zip).decode()
        _run_in_sandbox(
            sb,
            "python3",
            "-c",
            f"import base64,zipfile,io; "
            f"data=base64.b64decode('{b64_zip}'); "
            f"zipfile.ZipFile(io.BytesIO(data)).extractall('{skill_path}')",
        )

        # Install Python deps if pyproject.toml exists
        _run_in_sandbox(
            sb,
            "python3",
            "-c",
            f"import os,subprocess; "
            f"os.path.isfile('{skill_path}/pyproject.toml') and "
            f"subprocess.run(['uv','sync','--directory','{skill_path}'])",
        )

        return sb, skill_path


def run_eval_case_in_sandbox(
    skill_zip: bytes,
    prompt: str,
    agent_config: AgentSandboxConfig,
    agent_env_vars: dict[str, str],
    org_slug: str,
    skill_name: str,
) -> tuple[str, str, int, int]:
    """Run a single eval case in a Modal sandbox.

    Steps:
    1. Build an agent-specific image
    2. Create a Modal sandbox with the image and env vars
    3. Upload and extract the skill zip to the agent's skills path
    4. Invoke the agent CLI with the prompt and capture output
    5. Return stdout, stderr, exit code, and duration

    Args:
        skill_zip: Raw bytes of the skill zip archive.
        prompt: The eval case prompt to send to the agent.
        agent_config: Configuration for the target agent.
        agent_env_vars: Decrypted environment variables (API keys).
        org_slug: Organisation slug for skill path placement.
        skill_name: Skill name for skill path placement.

    Returns:
        Tuple of (stdout, stderr, exit_code, duration_ms).
    """
    import time

    sb, skill_path = _create_skill_sandbox(
        skill_zip, agent_config, agent_env_vars, org_slug, skill_name
    )

    try:
        # Run the eval prompt through the agent
        cmd = build_agent_run_command(agent_config, prompt)
        start = time.monotonic()
        stdout, exit_code = _run_in_sandbox(sb, *cmd)
        duration_ms = int((time.monotonic() - start) * 1000)

        return stdout, "", exit_code, duration_ms
    finally:
        sb.terminate()
