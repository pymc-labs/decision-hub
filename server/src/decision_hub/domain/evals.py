"""Agent-aware eval orchestration for skills.

Orchestrates running eval cases in agent sandboxes and judging results with an LLM.
Each case goes through: sandbox execution -> exit code check -> LLM judge.
"""

from decision_hub.infra.anthropic_client import judge_eval_output
from decision_hub.infra.modal_client import get_agent_config, run_eval_case_in_sandbox
from decision_hub.models import EvalCase, EvalConfig


def run_eval_pipeline(
    skill_zip: bytes,
    eval_config: EvalConfig,
    eval_cases: tuple[EvalCase, ...],
    agent_env_vars: dict[str, str],
    org_slug: str,
    skill_name: str,
    runtime=None,
) -> tuple[list[dict], int, int, int]:
    """Execute eval cases in Modal sandbox and judge outputs.

    For each case:
    1. Run in sandbox -> (stdout, stderr, exit_code, duration_ms)
       If sandbox crashes: stage="sandbox", verdict="error"
    2. Check exit code: non-zero -> stage="agent", verdict="error", skip judge
    3. Judge output with LLM -> verdict + reasoning
       If judge fails: stage="judge", verdict="error"

    Args:
        skill_zip: Raw bytes of the skill zip archive.
        eval_config: Eval configuration from SKILL.md (agent, judge_model).
        eval_cases: Tuple of parsed eval cases.
        agent_env_vars: Decrypted environment variables (API keys).
        org_slug: Organization slug.
        skill_name: Skill name.
        runtime: Optional RuntimeConfig (reserved for future use).

    Returns:
        Tuple of (case_results, passed_count, total_count, total_duration_ms).
    """
    agent_config = get_agent_config(eval_config.agent)

    case_results: list[dict] = []
    passed = 0
    total_duration_ms = 0

    for case in eval_cases:
        # Stage 1: Run in sandbox
        try:
            stdout, stderr, exit_code, duration_ms = run_eval_case_in_sandbox(
                skill_zip=skill_zip,
                prompt=case.prompt,
                agent_config=agent_config,
                agent_env_vars=agent_env_vars,
                org_slug=org_slug,
                skill_name=skill_name,
            )
        except Exception as e:
            case_results.append({
                "name": case.name,
                "description": case.description,
                "verdict": "error",
                "reasoning": f"Sandbox error: {e}",
                "agent_output": "",
                "agent_stderr": "",
                "exit_code": -1,
                "duration_ms": 0,
                "stage": "sandbox",
            })
            continue

        total_duration_ms += duration_ms

        # Stage 2: Check exit code — non-zero means agent failed
        if exit_code != 0:
            case_results.append({
                "name": case.name,
                "description": case.description,
                "verdict": "error",
                "reasoning": f"Agent exited with code {exit_code}: {stderr}",
                "agent_output": stdout,
                "agent_stderr": stderr,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "stage": "agent",
            })
            continue

        # Stage 3: Judge the output with LLM
        try:
            judgment = judge_eval_output(
                api_key=agent_env_vars.get(agent_config.key_env_var, ""),
                model=eval_config.judge_model,
                eval_case_name=case.name,
                eval_criteria=case.judge_criteria,
                agent_output=stdout,
            )
            verdict = judgment["verdict"]
            reasoning = judgment["reasoning"]
            stage = "judge"
        except Exception as e:
            verdict = "error"
            reasoning = f"Judge error: {e}"
            stage = "judge"

        if verdict == "pass":
            passed += 1

        case_results.append({
            "name": case.name,
            "description": case.description,
            "verdict": verdict,
            "reasoning": reasoning,
            "agent_output": stdout,
            "agent_stderr": stderr,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "stage": stage,
        })

    return case_results, passed, len(eval_cases), total_duration_ms
