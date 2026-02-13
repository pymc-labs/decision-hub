"""Agent-aware assessment orchestration for skills.

Orchestrates running assessment cases in agent sandboxes and judging results with an LLM.
Each case goes through: sandbox execution -> exit code check -> LLM judge.

Two pipelines:
- run_eval_pipeline(): original batch mode (no streaming, used as fallback)
- run_streaming_eval(): streaming mode with S3 log persistence and DB heartbeats
"""

import json
import re
import time
from collections.abc import Generator
from datetime import UTC, datetime
from uuid import UUID

from loguru import logger

from decision_hub.infra.anthropic_client import judge_eval_output
from decision_hub.infra.modal_client import get_agent_config, run_eval_case_in_sandbox, stream_eval_case_in_sandbox
from decision_hub.models import EvalCase, EvalConfig

# Patterns to redact from event content (API key fragments)
_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[a-zA-Z0-9\-_]{20,}"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"AIza[a-zA-Z0-9\-_]{30,}"),
]

# Maximum size for individual event content (10 KB)
_MAX_CONTENT_LEN = 10 * 1024


def _redact_secrets(text: str) -> str:
    """Replace known API key patterns with [REDACTED]."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def _truncate(text: str, max_len: int = _MAX_CONTENT_LEN) -> str:
    """Truncate text to max_len, appending an indicator if truncated."""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "...[truncated]"


def _make_event(seq: int, event_type: str, **kwargs) -> dict:
    """Create a structured event dict with seq, type, and timestamp."""
    event = {
        "seq": seq,
        "type": event_type,
        "ts": datetime.now(UTC).isoformat(),
        **kwargs,
    }
    # Redact and truncate content fields
    if "content" in event and isinstance(event["content"], str):
        event["content"] = _truncate(_redact_secrets(event["content"]))
    if "reasoning" in event and isinstance(event["reasoning"], str):
        event["reasoning"] = _truncate(_redact_secrets(event["reasoning"]))
    return event


def run_eval_pipeline(
    skill_zip: bytes,
    eval_config: EvalConfig,
    eval_cases: tuple[EvalCase, ...],
    agent_env_vars: dict[str, str],
    org_slug: str,
    skill_name: str,
    runtime=None,
    judge_api_key: str = "",
    *,
    sandbox_memory_mb: int = 4096,
    sandbox_timeout_seconds: int = 900,
    sandbox_cpu: float = 2.0,
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
        judge_api_key: Anthropic API key for the LLM judge (from the
            user's stored keys). Required — the judge always calls the
            Anthropic API regardless of which agent is being evaluated.

    Returns:
        Tuple of (case_results, passed_count, total_count, total_duration_ms).
    """
    agent_config = get_agent_config(eval_config.agent)

    logger.info("Starting eval pipeline: {} cases, agent={}", len(eval_cases), eval_config.agent)

    case_results: list[dict] = []
    passed = 0
    total_duration_ms = 0

    for case in eval_cases:
        # Stage 1: Run in sandbox
        logger.info("Running eval case '{}' in sandbox", case.name)
        try:
            stdout, stderr, exit_code, duration_ms = run_eval_case_in_sandbox(
                skill_zip=skill_zip,
                prompt=case.prompt,
                agent_config=agent_config,
                agent_env_vars=agent_env_vars,
                org_slug=org_slug,
                skill_name=skill_name,
                sandbox_memory_mb=sandbox_memory_mb,
                sandbox_timeout_seconds=sandbox_timeout_seconds,
                sandbox_cpu=sandbox_cpu,
            )
        except Exception as e:
            logger.error("Sandbox error for case '{}': {}", case.name, e)
            case_results.append(
                {
                    "name": case.name,
                    "description": case.description,
                    "verdict": "error",
                    "reasoning": _redact_secrets(f"Sandbox error: {e}"),
                    "agent_output": "",
                    "agent_stderr": "",
                    "exit_code": -1,
                    "duration_ms": 0,
                    "stage": "sandbox",
                }
            )
            continue

        total_duration_ms += duration_ms
        logger.debug(
            "Case '{}': exit_code={} duration={}ms stdout_len={}", case.name, exit_code, duration_ms, len(stdout)
        )

        # Stage 2: Check exit code — non-zero means agent failed
        if exit_code != 0:
            case_results.append(
                {
                    "name": case.name,
                    "description": case.description,
                    "verdict": "error",
                    "reasoning": _redact_secrets(f"Agent exited with code {exit_code}: {stderr}"),
                    "agent_output": _redact_secrets(stdout),
                    "agent_stderr": _redact_secrets(stderr),
                    "exit_code": exit_code,
                    "duration_ms": duration_ms,
                    "stage": "agent",
                }
            )
            continue

        # Stage 3: Judge the output with LLM
        logger.info("Judging case '{}' with model={}", case.name, eval_config.judge_model)
        try:
            judgment = judge_eval_output(
                api_key=judge_api_key,
                model=eval_config.judge_model,
                eval_case_name=case.name,
                eval_criteria=case.judge_criteria,
                agent_output=stdout,
            )
            verdict = judgment["verdict"]
            reasoning = judgment["reasoning"]
            stage = "judge"
        except Exception as e:
            logger.error("Judge error for case '{}': {}", case.name, e)
            verdict = "error"
            reasoning = f"Judge error: {e}"
            stage = "judge"

        if verdict == "pass":
            passed += 1

        case_results.append(
            {
                "name": case.name,
                "description": case.description,
                "verdict": verdict,
                "reasoning": _redact_secrets(reasoning),
                "agent_output": _redact_secrets(stdout),
                "agent_stderr": _redact_secrets(stderr),
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "stage": stage,
            }
        )

    return case_results, passed, len(eval_cases), total_duration_ms


# ---------------------------------------------------------------------------
# Streaming pipeline with S3 persistence
# ---------------------------------------------------------------------------


def stream_eval_pipeline(
    skill_zip: bytes,
    eval_config: EvalConfig,
    eval_cases: tuple[EvalCase, ...],
    agent_env_vars: dict[str, str],
    org_slug: str,
    skill_name: str,
    judge_api_key: str = "",
    *,
    sandbox_memory_mb: int = 4096,
    sandbox_timeout_seconds: int = 900,
    sandbox_cpu: float = 2.0,
) -> Generator[dict, None, None]:
    """Generator that yields structured events for the entire pipeline.

    Event types: setup, case_start, log, judge_start, case_result, report.
    Each event has a monotonically increasing seq number.
    """
    agent_config = get_agent_config(eval_config.agent)

    seq = 0
    case_results: list[dict] = []
    passed = 0
    total_duration_ms = 0

    seq += 1
    yield _make_event(
        seq, "setup", content=f"Starting assessment: {len(eval_cases)} case(s), agent={eval_config.agent}"
    )

    for case_idx, case in enumerate(eval_cases):
        seq += 1
        yield _make_event(
            seq,
            "case_start",
            case_index=case_idx,
            case_name=case.name,
            total_cases=len(eval_cases),
        )

        # Stage 1: Run agent in sandbox with streaming
        stdout = ""
        stderr = ""
        exit_code = -1
        duration_ms = 0

        try:
            gen = stream_eval_case_in_sandbox(
                skill_zip=skill_zip,
                prompt=case.prompt,
                agent_config=agent_config,
                agent_env_vars=agent_env_vars,
                org_slug=org_slug,
                skill_name=skill_name,
                sandbox_memory_mb=sandbox_memory_mb,
                sandbox_timeout_seconds=sandbox_timeout_seconds,
                sandbox_cpu=sandbox_cpu,
            )
            # Consume streaming output events
            try:
                while True:
                    output_event = next(gen)
                    seq += 1
                    yield _make_event(
                        seq,
                        "log",
                        stream=output_event["stream"],
                        case_index=case_idx,
                        content=output_event["content"],
                    )
            except StopIteration as stop:
                # Generator return value contains final results
                if stop.value is not None:
                    stdout, stderr, exit_code, duration_ms = stop.value
        except Exception as e:
            case_results.append(
                {
                    "name": case.name,
                    "description": case.description,
                    "verdict": "error",
                    "reasoning": _redact_secrets(f"Sandbox error: {e}"),
                    "agent_output": "",
                    "agent_stderr": "",
                    "exit_code": -1,
                    "duration_ms": 0,
                    "stage": "sandbox",
                }
            )
            seq += 1
            yield _make_event(
                seq,
                "case_result",
                case_index=case_idx,
                case_name=case.name,
                verdict="error",
                reasoning=_redact_secrets(f"Sandbox error: {e}"),
                duration_ms=0,
            )
            continue

        total_duration_ms += duration_ms

        # Stage 2: Check exit code
        if exit_code != 0:
            reasoning = _redact_secrets(f"Agent exited with code {exit_code}: {stderr[:500]}")
            case_results.append(
                {
                    "name": case.name,
                    "description": case.description,
                    "verdict": "error",
                    "reasoning": reasoning,
                    "agent_output": _redact_secrets(stdout),
                    "agent_stderr": _redact_secrets(stderr),
                    "exit_code": exit_code,
                    "duration_ms": duration_ms,
                    "stage": "agent",
                }
            )
            seq += 1
            yield _make_event(
                seq,
                "case_result",
                case_index=case_idx,
                case_name=case.name,
                verdict="error",
                reasoning=reasoning,
                duration_ms=duration_ms,
            )
            continue

        # Stage 3: Judge output with LLM
        seq += 1
        yield _make_event(seq, "judge_start", case_index=case_idx, case_name=case.name)

        try:
            judgment = judge_eval_output(
                api_key=judge_api_key,
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

        case_results.append(
            {
                "name": case.name,
                "description": case.description,
                "verdict": verdict,
                "reasoning": _redact_secrets(reasoning),
                "agent_output": _redact_secrets(stdout),
                "agent_stderr": _redact_secrets(stderr),
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "stage": stage,
            }
        )

        seq += 1
        yield _make_event(
            seq,
            "case_result",
            case_index=case_idx,
            case_name=case.name,
            verdict=verdict,
            reasoning=_redact_secrets(reasoning),
            duration_ms=duration_ms,
        )

    # Final summary event
    all_passed = all(r["verdict"] == "pass" for r in case_results)
    status = "completed" if all_passed else "failed"

    seq += 1
    yield _make_event(
        seq,
        "report",
        passed=passed,
        total=len(eval_cases),
        status=status,
        total_duration_ms=total_duration_ms,
        case_results=case_results,
    )


def run_streaming_eval(
    run_id: UUID,
    version_id: UUID,
    skill_zip: bytes,
    eval_config: EvalConfig,
    eval_cases: tuple[EvalCase, ...],
    agent_env_vars: dict[str, str],
    org_slug: str,
    skill_name: str,
    judge_api_key: str,
    database_url: str,
    s3_client,
    s3_bucket: str,
    log_s3_prefix: str,
    *,
    sandbox_memory_mb: int = 4096,
    sandbox_timeout_seconds: int = 900,
    sandbox_cpu: float = 2.0,
) -> None:
    """Consume the streaming pipeline, persist events to S3, and update DB.

    Batches events and writes S3 chunks every 2 seconds.
    Updates eval_runs heartbeat and status periodically.
    On completion, writes the eval_reports row (same as original pipeline).
    """
    from decision_hub.infra.database import (
        create_engine,
        insert_eval_report,
        update_eval_run_status,
    )
    from decision_hub.infra.storage import upload_eval_log_chunk

    engine = create_engine(database_url)
    logger.info("Starting streaming eval run_id={} ({} cases)", run_id, len(eval_cases))

    # Mark run as provisioning
    with engine.connect() as conn:
        update_eval_run_status(conn, run_id, status="provisioning", stage="setup")
        conn.commit()

    event_buffer: list[dict] = []
    chunk_seq = 0
    last_flush_time = time.monotonic()
    last_heartbeat_time = time.monotonic()
    final_report_event: dict | None = None

    def _flush_buffer():
        nonlocal chunk_seq, last_flush_time
        if not event_buffer:
            return
        chunk_seq += 1
        events_jsonl = "\n".join(json.dumps(e) for e in event_buffer) + "\n"
        upload_eval_log_chunk(s3_client, s3_bucket, log_s3_prefix, chunk_seq, events_jsonl)
        event_buffer.clear()
        last_flush_time = time.monotonic()

    def _update_heartbeat(**kwargs):
        nonlocal last_heartbeat_time
        with engine.connect() as conn:
            update_eval_run_status(conn, run_id, log_seq=chunk_seq, **kwargs)
            conn.commit()
        last_heartbeat_time = time.monotonic()

    try:
        pipeline = stream_eval_pipeline(
            skill_zip=skill_zip,
            eval_config=eval_config,
            eval_cases=eval_cases,
            agent_env_vars=agent_env_vars,
            org_slug=org_slug,
            skill_name=skill_name,
            judge_api_key=judge_api_key,
            sandbox_memory_mb=sandbox_memory_mb,
            sandbox_timeout_seconds=sandbox_timeout_seconds,
            sandbox_cpu=sandbox_cpu,
        )

        for event in pipeline:
            event_buffer.append(event)

            # Track the final report event for DB storage
            if event["type"] == "report":
                final_report_event = event

            # Update DB status on stage transitions
            if event["type"] == "case_start":
                _update_heartbeat(
                    status="running",
                    stage="agent",
                    current_case=event.get("case_name"),
                    current_case_index=event.get("case_index"),
                )
            elif event["type"] == "judge_start":
                _update_heartbeat(status="judging", stage="judge")

            # Flush buffer every 2 seconds
            now = time.monotonic()
            if now - last_flush_time >= 2.0:
                _flush_buffer()

            # Heartbeat every 30 seconds (without stage change)
            if now - last_heartbeat_time >= 30.0:
                _update_heartbeat()

        # Final flush
        _flush_buffer()

        # Write eval_reports row (same as original pipeline)
        if final_report_event:
            case_results = final_report_event["case_results"]
            passed = final_report_event["passed"]
            total = final_report_event["total"]
            total_duration_ms = final_report_event["total_duration_ms"]
            all_passed = all(r["verdict"] == "pass" for r in case_results)
            status = "completed" if all_passed else "failed"

            with engine.connect() as conn:
                insert_eval_report(
                    conn,
                    version_id=version_id,
                    agent=eval_config.agent,
                    judge_model=eval_config.judge_model,
                    case_results=case_results,
                    passed=passed,
                    total=total,
                    total_duration_ms=total_duration_ms,
                    status=status,
                )
                update_eval_run_status(
                    conn,
                    run_id,
                    status=status,
                    log_seq=chunk_seq,
                    completed_at=datetime.now(UTC),
                )
                conn.commit()

    except Exception as e:
        logger.error("Streaming eval failed for run_id={}: {}", run_id, e)
        # Flush any remaining events
        _flush_buffer()

        # Mark run as failed
        with engine.connect() as conn:
            update_eval_run_status(
                conn,
                run_id,
                status="failed",
                error_message=str(e),
                log_seq=chunk_seq,
                completed_at=datetime.now(UTC),
            )
            conn.commit()
        raise
