"""Modal sandbox management for agent-aware skill evaluations.

Provides functions to build agent-specific container images and run
skill tests inside Modal sandboxes with injected API keys.
"""

import shlex
from dataclasses import dataclass

from loguru import logger

from decision_hub.models import AgentSandboxConfig


# ---------------------------------------------------------------------------
# Agent configurations
# ---------------------------------------------------------------------------

AGENT_CONFIGS: dict[str, AgentSandboxConfig] = {
    "claude": AgentSandboxConfig(
        npm_package="@anthropic-ai/claude-code",
        skills_path=".claude/skills",
        run_cmd=("claude", "-p", "--dangerously-skip-permissions"),
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


# Lightweight validation endpoints per provider.
# Each maps key_env_var -> (url, headers_builder, method).
_KEY_VALIDATION = {
    "ANTHROPIC_API_KEY": {
        "url": "https://api.anthropic.com/v1/models",
        "headers": lambda key: {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    },
}


def validate_api_key(key_env_var: str, key_value: str) -> None:
    """Validate an API key with a lightweight request before sandbox launch.

    Raises ValueError with a clear message if the key is invalid, so the
    eval pipeline fails fast instead of hanging for 15 minutes in a sandbox.
    """
    import httpx

    spec = _KEY_VALIDATION.get(key_env_var)
    if spec is None:
        return  # No validation endpoint known for this provider

    try:
        resp = httpx.get(spec["url"], headers=spec["headers"](key_value), timeout=10)
    except httpx.HTTPError as e:
        logger.warning("Network error validating {}: {}", key_env_var, e)
        return  # Don't block on transient network issues

    if resp.status_code == 401:
        raise ValueError(
            f"{key_env_var} is invalid (HTTP 401). "
            f"The stored key may be expired or revoked. "
            f"Update it and retry."
        )


def _extract_skill_body(skill_zip: bytes) -> str:
    """Extract the SKILL.md body (system prompt) from a skill zip archive."""
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(skill_zip)) as zf:
        for name in zf.namelist():
            if name.endswith("SKILL.md"):
                content = zf.read(name).decode("utf-8")
                # Body is everything after the closing --- delimiter
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    return parts[2].strip()
    return ""


def _write_claude_md_from_skill_zip(
    sb, skill_zip: bytes, home_dir: str, skill_path: str,
) -> None:
    """Write the SKILL.md body as CLAUDE.md in the sandbox project root.

    Claude Code reads CLAUDE.md as project instructions, providing the
    skill's system prompt context to the agent during eval runs.
    Prepends the skill directory path so the agent knows where to find files.
    """
    import base64

    body = _extract_skill_body(skill_zip)
    if not body:
        return

    # Prepend skill directory context so the agent can find scripts
    # and uses the pre-installed venv instead of system Python
    full_body = (
        f"## Skill directory\n\n"
        f"The skill files (scripts, data, configs) are located at: `{skill_path}`\n"
        f"Always `cd {skill_path}` before running any scripts.\n\n"
        f"## Python environment\n\n"
        f"A virtual environment with all dependencies pre-installed exists at "
        f"`{skill_path}/.venv`. Always use `{skill_path}/.venv/bin/python` to "
        f"run Python scripts. Do NOT use `python3` or `python` directly — "
        f"the system Python does not have the required packages.\n\n"
        f"Example: `{skill_path}/.venv/bin/python {skill_path}/run_ab_test.py`\n\n"
        f"{body}"
    )

    b64_body = base64.b64encode(full_body.encode()).decode()
    _run_in_sandbox(
        sb, "python3", "-c",
        f"import base64; "
        f"open('{home_dir}/CLAUDE.md', 'w').write("
        f"base64.b64decode('{b64_body}').decode())",
    )
    logger.debug("Wrote CLAUDE.md ({} chars)", len(full_body))


# ---------------------------------------------------------------------------
# Modal image building
# ---------------------------------------------------------------------------


def build_eval_image(config: AgentSandboxConfig):
    """Build a Modal image for a specific agent.

    The image is based on node:20-slim with the agent's NPM package
    installed globally, plus uv for Python dependency management.
    A non-root user 'sandbox' is created because Claude Code refuses
    --dangerously-skip-permissions when running as root.

    Returns:
        A modal.Image configured for the agent.
    """
    import modal

    return (
        modal.Image.from_registry("node:20-slim")
        .apt_install("python3", "python3-pip", "curl", "git")
        .run_commands(
            f"npm install -g {config.npm_package}",
            "pip install uv --break-system-packages",
            "useradd -m -s /bin/bash sandbox",
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
    run_fn = getattr(sb, "exec", None) or sb.process
    proc = run_fn(*args)
    proc.wait()
    return proc.stdout.read(), proc.returncode


def _run_agent_in_sandbox(
    sb, shell_cmd: str, skill_path: str = "",
    poll_interval: int = 5, max_wait: int = 840,
) -> tuple[str, str, int, int]:
    """Run an agent command as the sandbox user with file-based I/O capture.

    Modal sandbox hangs when running agents like Claude Code in the
    foreground because of I/O pipe handling issues with su/process.
    This function works around it by backgrounding the process with nohup,
    polling for completion, and reading output from files.

    Returns (stdout, stderr, exit_code, duration_ms).
    """
    import time

    out_file = "/tmp/agent_stdout.txt"
    err_file = "/tmp/agent_stderr.txt"
    rc_file = "/tmp/agent_rc.txt"
    pid_file = "/tmp/agent_pid.txt"

    # Build PATH with the skill's venv/bin so `python` resolves to the
    # venv interpreter with installed deps.
    path_prefix = ""
    if skill_path:
        path_prefix = f"export PATH={skill_path}/.venv/bin:$PATH && "

    # Launch agent in background, capture output to files, write exit code
    # when done. Use su -m to preserve env vars (API keys from Modal secrets).
    # cd $HOME first so Claude Code discovers CLAUDE.md as project instructions.
    #
    # The agent command is written to a separate inner script to avoid
    # nested shell quoting issues with su -c. This prevents prompt content
    # containing quotes from breaking out of the shell command.
    inner_script = (
        f"#!/bin/bash\n"
        f"{path_prefix}cd $HOME && {shell_cmd}\n"
    )
    launch_script = (
        f"#!/bin/bash\n"
        f"su -m sandbox /tmp/run_inner.sh > {out_file} 2> {err_file}\n"
        f"echo $? > {rc_file}\n"
    )
    # Write the inner script (agent command) and outer script (su wrapper).
    # Using quoted heredoc (<<'EOF') prevents shell expansion of script contents.
    _run_in_sandbox(sb, "bash", "-c", f"cat > /tmp/run_inner.sh << 'INNER_EOF'\n{inner_script}INNER_EOF\nchmod +x /tmp/run_inner.sh")
    _run_in_sandbox(sb, "bash", "-c", f"cat > /tmp/run_agent.sh << 'SCRIPT_EOF'\n{launch_script}SCRIPT_EOF\nchmod +x /tmp/run_agent.sh")
    _run_in_sandbox(sb, "bash", "-c", f"nohup /tmp/run_agent.sh &\necho $! > {pid_file}")

    start = time.monotonic()
    elapsed = 0

    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed = time.monotonic() - start

        # Check if the exit code file exists (process finished)
        check_stdout, _ = _run_in_sandbox(
            sb, "bash", "-c", f"cat {rc_file} 2>/dev/null || echo RUNNING",
        )
        status = check_stdout.strip()
        if status != "RUNNING":
            break
    else:
        # Timed out waiting for agent
        logger.warning("Agent timed out after {}s, killing", max_wait)
        _run_in_sandbox(
            sb, "bash", "-c",
            f"kill $(cat {pid_file} 2>/dev/null) 2>/dev/null; echo 137 > {rc_file}",
        )

    duration_ms = int((time.monotonic() - start) * 1000)

    # Read captured output
    stdout, _ = _run_in_sandbox(sb, "bash", "-c", f"cat {out_file} 2>/dev/null")
    stderr, _ = _run_in_sandbox(sb, "bash", "-c", f"cat {err_file} 2>/dev/null")
    rc_str, _ = _run_in_sandbox(sb, "bash", "-c", f"cat {rc_file} 2>/dev/null")

    try:
        exit_code = int(rc_str.strip())
    except (ValueError, AttributeError):
        exit_code = -1

    return stdout, stderr, exit_code, duration_ms


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

    logger.info("Building sandbox image for agent={}", agent_config.npm_package)
    image = build_eval_image(agent_config)

    # Merge agent-specific extra env with the user's decrypted keys
    env = {**agent_config.extra_env, **agent_env_vars}

    app = modal.App.lookup("decision-hub-eval", create_if_missing=True)
    # Use /home/sandbox as the home dir — Claude Code refuses
    # --dangerously-skip-permissions when running as root.
    home_dir = "/home/sandbox"
    skill_path = f"{home_dir}/{agent_config.skills_path}/{org_slug}/{skill_name}"

    # Add HOME to env so tools resolve paths correctly
    env["HOME"] = home_dir

    logger.info("Creating sandbox (memory=4096, timeout=900)")
    sb = modal.Sandbox.create(
        image=image,
        secrets=[modal.Secret.from_dict(env)],
        app=app,
        memory=4096,
        timeout=900,
    )

    # Set up skill directory (as root, then chown to sandbox user)
    logger.debug("Creating skill dir: {}", skill_path)
    _run_in_sandbox(sb, "mkdir", "-p", skill_path)

    # Transfer and extract skill zip via base64 + Python zipfile
    logger.info("Transferring skill zip ({} bytes)", len(skill_zip))
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
    logger.info("Installing deps (uv sync if pyproject.toml exists)")
    stdout, exit_code = _run_in_sandbox(
        sb,
        "bash",
        "-c",
        f"if [ -f '{skill_path}/pyproject.toml' ]; then "
        f"echo 'pyproject.toml found, running uv sync'; "
        f"uv sync --directory '{skill_path}' 2>&1; "
        f"echo 'uv sync exit code:' $?; "
        f"else echo 'No pyproject.toml found'; fi",
    )
    logger.info("Dep install result: exit={} stdout={}", exit_code, stdout[:500])

    # Verify the venv was actually created and has a python binary
    verify_stdout, _ = _run_in_sandbox(
        sb, "bash", "-c",
        f"ls -la {skill_path}/.venv/bin/python 2>&1 && "
        f"{skill_path}/.venv/bin/python --version 2>&1",
    )
    logger.debug("Venv check: {}", verify_stdout.strip())

    # Extract SKILL.md body and write it as CLAUDE.md at the project root.
    # Claude Code reads CLAUDE.md as project instructions (system prompt).
    _write_claude_md_from_skill_zip(sb, skill_zip, home_dir, skill_path)

    # Initialize a git repo so Claude Code recognizes the project root
    _run_in_sandbox(sb, "bash", "-c",
        f"cd {home_dir} && git init -q "
        f"&& git config user.email 'eval@decision-hub' "
        f"&& git config user.name 'eval' "
        f"&& git add -A && git commit -q -m init")

    # Make everything owned by sandbox user so agent runs as non-root
    _run_in_sandbox(sb, "chown", "-R", "sandbox:sandbox", home_dir)

    logger.info("Sandbox ready for {}/{}", org_slug, skill_name)
    return sb, skill_path


# ---------------------------------------------------------------------------
# Monitor script for real-time sandbox output streaming
# ---------------------------------------------------------------------------

# Embedded Python script that runs as root inside the sandbox.
# Tails agent stdout/stderr files using seek offsets and prints structured
# lines that the parent process can parse. Exits when the agent writes its
# exit code file or timeout is reached.
# NOTE: This script runs INSIDE the sandbox — it uses print() for the
# structured protocol (OUT:/ERR:/RC:), not for logging.
MONITOR_SCRIPT = r"""
import base64
import os
import sys
import time

OUT_FILE = "/tmp/agent_stdout.txt"
ERR_FILE = "/tmp/agent_stderr.txt"
RC_FILE = "/tmp/agent_rc.txt"
POLL_INTERVAL = 0.5
TIMEOUT = int(sys.argv[1]) if len(sys.argv) > 1 else 840

out_pos = 0
err_pos = 0
start = time.monotonic()

while (time.monotonic() - start) < TIMEOUT:
    # Read new stdout content
    if os.path.exists(OUT_FILE):
        with open(OUT_FILE, "rb") as f:
            f.seek(out_pos)
            chunk = f.read()
            if chunk:
                out_pos += len(chunk)
                print("OUT:" + base64.b64encode(chunk).decode(), flush=True)

    # Read new stderr content
    if os.path.exists(ERR_FILE):
        with open(ERR_FILE, "rb") as f:
            f.seek(err_pos)
            chunk = f.read()
            if chunk:
                err_pos += len(chunk)
                print("ERR:" + base64.b64encode(chunk).decode(), flush=True)

    # Check if agent is done
    if os.path.exists(RC_FILE):
        # Final flush of remaining output
        time.sleep(0.2)
        if os.path.exists(OUT_FILE):
            with open(OUT_FILE, "rb") as f:
                f.seek(out_pos)
                chunk = f.read()
                if chunk:
                    print("OUT:" + base64.b64encode(chunk).decode(), flush=True)
        if os.path.exists(ERR_FILE):
            with open(ERR_FILE, "rb") as f:
                f.seek(err_pos)
                chunk = f.read()
                if chunk:
                    print("ERR:" + base64.b64encode(chunk).decode(), flush=True)

        with open(RC_FILE) as f:
            rc = f.read().strip()
        print("RC:" + rc, flush=True)
        sys.exit(0)

    time.sleep(POLL_INTERVAL)

# Timeout reached
print("RC:137", flush=True)
"""


def stream_eval_case_in_sandbox(
    skill_zip: bytes,
    prompt: str,
    agent_config: AgentSandboxConfig,
    agent_env_vars: dict[str, str],
    org_slug: str,
    skill_name: str,
):
    """Run a single eval case and yield structured output events.

    Yields dicts with keys: stream ("stdout"|"stderr"), content (str).
    Returns the final result as a dict with: stdout, stderr, exit_code, duration_ms.

    The generator protocol: yield output events, then return the final result
    via StopIteration.value.
    """
    import base64
    import time

    sb, skill_path = _create_skill_sandbox(
        skill_zip, agent_config, agent_env_vars, org_slug, skill_name
    )

    try:
        # Launch agent (same approach as _run_agent_in_sandbox)
        cmd = build_agent_run_command(agent_config, prompt)
        shell_cmd = " ".join(shlex.quote(c) for c in cmd)
        logger.info("Streaming agent execution: {} (prompt_len={})", cmd[0], len(prompt))

        out_file = "/tmp/agent_stdout.txt"
        err_file = "/tmp/agent_stderr.txt"
        rc_file = "/tmp/agent_rc.txt"
        pid_file = "/tmp/agent_pid.txt"

        path_prefix = ""
        if skill_path:
            path_prefix = f"export PATH={skill_path}/.venv/bin:$PATH && "

        inner_script = (
            f"#!/bin/bash\n"
            f"{path_prefix}cd $HOME && {shell_cmd}\n"
        )
        launch_script = (
            f"#!/bin/bash\n"
            f"su -m sandbox /tmp/run_inner.sh > {out_file} 2> {err_file}\n"
            f"echo $? > {rc_file}\n"
        )
        _run_in_sandbox(sb, "bash", "-c", f"cat > /tmp/run_inner.sh << 'INNER_EOF'\n{inner_script}INNER_EOF\nchmod +x /tmp/run_inner.sh")
        _run_in_sandbox(sb, "bash", "-c", f"cat > /tmp/run_agent.sh << 'SCRIPT_EOF'\n{launch_script}SCRIPT_EOF\nchmod +x /tmp/run_agent.sh")
        _run_in_sandbox(sb, "bash", "-c", f"nohup /tmp/run_agent.sh &\necho $! > {pid_file}")

        start = time.monotonic()

        # Launch monitor script that tails output files
        monitor_proc = sb.exec("python3", "-c", MONITOR_SCRIPT, "840")

        full_stdout = []
        full_stderr = []
        exit_code = -1

        for line in monitor_proc.stdout:
            line = line.rstrip("\n")
            if line.startswith("OUT:"):
                chunk = base64.b64decode(line[4:]).decode("utf-8", errors="replace")
                full_stdout.append(chunk)
                yield {"stream": "stdout", "content": chunk}
            elif line.startswith("ERR:"):
                chunk = base64.b64decode(line[4:]).decode("utf-8", errors="replace")
                full_stderr.append(chunk)
                yield {"stream": "stderr", "content": chunk}
            elif line.startswith("RC:"):
                try:
                    exit_code = int(line[3:].strip())
                except ValueError:
                    exit_code = -1
                break

        monitor_proc.wait()
        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info("Streaming agent finished: exit={} duration={}ms", exit_code, duration_ms)

        return "".join(full_stdout), "".join(full_stderr), exit_code, duration_ms
    finally:
        sb.terminate()


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
        # Run the prompt through the agent as non-root 'sandbox' user.
        # Claude Code refuses --dangerously-skip-permissions as root.
        cmd = build_agent_run_command(agent_config, prompt)
        shell_cmd = " ".join(shlex.quote(c) for c in cmd)
        logger.info("Running agent as sandbox user: {} (prompt_len={})", cmd[0], len(prompt))

        stdout, stderr, exit_code, duration_ms = _run_agent_in_sandbox(
            sb, shell_cmd, skill_path=skill_path,
        )
        logger.info(
            "Agent finished: exit={} duration={}ms stdout_len={}",
            exit_code, duration_ms, len(stdout),
        )

        return stdout, stderr, exit_code, duration_ms
    finally:
        sb.terminate()
