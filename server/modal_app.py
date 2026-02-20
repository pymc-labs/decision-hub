"""Modal deployment entry point for Decision Hub API."""

import os
from pathlib import Path

import modal

env = os.environ.get("DHUB_ENV", "dev")
suffix = "" if env == "prod" else f"-{env}"
app_name = f"decision-hub{suffix}"


def _read_env_value(key: str) -> str | None:
    """Read a value from env var or local .env file."""
    env_val = os.environ.get(key)
    if env_val is not None:
        return env_val
    env_file = Path(f".env.{env}")
    if not env_file.exists():
        return None
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return None


app = modal.App(app_name)

_frontend_dist = Path("../frontend/dist")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .add_local_dir("../shared", remote_path="/tmp/dhub-core", copy=True)
    .run_commands("pip install /tmp/dhub-core")
    .pip_install_from_pyproject("pyproject.toml")
    .add_local_dir("src/decision_hub", remote_path="/root/decision_hub", copy=True)
)

# Include the frontend build when it exists (produced by deploy script).
if _frontend_dist.is_dir():
    image = image.add_local_dir(
        str(_frontend_dist),
        remote_path="/root/frontend_dist",
        copy=True,
    )

secrets = [
    modal.Secret.from_name(f"decision-hub-db{suffix}"),
    modal.Secret.from_name(f"decision-hub-secrets{suffix}"),
    modal.Secret.from_name(f"decision-hub-aws{suffix}"),
    # Inject values from the local .env file that aren't in Modal secrets.
    # These are read at deploy time so server redeploys pick up changes
    # without needing to update Modal secrets manually.
    modal.Secret.from_dict(
        {
            "MODAL_APP_NAME": app_name,
            **({"MIN_CLI_VERSION": v} if (v := _read_env_value("MIN_CLI_VERSION")) else {}),
        }
    ),
]


custom_domains = ["hub.decision.ai"] if env == "prod" else ["hub-dev.decision.ai"]


@app.function(image=image, secrets=secrets, scaledown_window=300, cpu=0.5, memory=256)
@modal.concurrent(max_inputs=100)
@modal.asgi_app(label=f"api{suffix}", custom_domains=custom_domains)
def web():
    """Serve the Decision Hub FastAPI application."""
    from decision_hub.api.app import create_app

    return create_app()


@app.function(image=image, secrets=secrets, timeout=1800)
def run_eval_task(
    version_id: str,
    eval_agent: str,
    eval_judge_model: str,
    eval_cases_dicts: list[dict],
    s3_key: str,
    s3_bucket: str,
    org_slug: str,
    skill_name: str,
    user_id: str,
    eval_run_id: str | None = None,
):
    """Run agent assessment in its own Modal container.

    Spawned asynchronously from the publish endpoint so the assessment
    has its own lifecycle and doesn't get killed when the web
    container scales down.

    Downloads the skill zip from S3 instead of receiving it as a
    parameter, avoiding 50 MB payloads in Modal's parameter transport.
    """
    from uuid import UUID

    from loguru import logger

    from decision_hub.api.registry_service import run_assessment_background
    from decision_hub.infra.storage import create_s3_client
    from decision_hub.logging import setup_logging
    from decision_hub.models import EvalCase, EvalConfig
    from decision_hub.settings import create_settings

    settings = create_settings()
    setup_logging(settings.log_level)

    logger.info(
        "Starting eval task for {}/{} version={} run={} agent={} cases={}",
        org_slug,
        skill_name,
        version_id,
        eval_run_id,
        eval_agent,
        len(eval_cases_dicts),
    )

    logger.info("Downloading skill zip from s3://{}/{}", s3_bucket, s3_key)
    s3_client = create_s3_client(
        region=settings.aws_region,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
    )
    response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
    skill_zip = response["Body"].read()
    logger.info("Downloaded {} bytes", len(skill_zip))

    config = EvalConfig(agent=eval_agent, judge_model=eval_judge_model)
    cases = tuple(
        EvalCase(
            name=d["name"],
            description=d["description"],
            prompt=d["prompt"],
            judge_criteria=d["judge_criteria"],
        )
        for d in eval_cases_dicts
    )

    run_assessment_background(
        version_id=UUID(version_id),
        assessment_config=config,
        assessment_cases=cases,
        skill_zip=skill_zip,
        org_slug=org_slug,
        skill_name=skill_name,
        settings=settings,
        user_id=UUID(user_id),
        run_id=UUID(eval_run_id) if eval_run_id else None,
    )

    logger.info("Eval task completed for {}/{}", org_slug, skill_name)


# Extended image for the crawler — adds git for cloning repos
crawler_image = image.apt_install("git")


@app.function(image=crawler_image, secrets=secrets, timeout=300, max_containers=50)
def crawl_process_repo(
    repo_dict: dict,
    bot_user_id: str,
    github_token: str | None = None,
) -> dict:
    """Process a single discovered repo: clone, discover skills, gauntlet, publish.

    Runs on Modal with ephemeral disk and access to DB/S3/Gemini secrets.
    Returns a result dict with status and counts.
    """
    from decision_hub.logging import setup_logging
    from decision_hub.scripts.crawler.processing import process_repo_on_modal
    from decision_hub.settings import create_settings

    settings = create_settings()
    setup_logging(settings.log_level)

    return process_repo_on_modal(repo_dict, bot_user_id, github_token)


@app.function(image=crawler_image, secrets=secrets, timeout=300, max_containers=20)
def tracker_process_repo(
    tracker_dict: dict,
    known_sha: str,
    github_token: str | None = None,
) -> dict:
    """Process a single tracked repo: clone, discover skills, gauntlet, publish.

    Runs on Modal with ephemeral disk and access to DB/S3/Gemini secrets.
    Returns a result dict with status, repo_url, and optional error.
    """
    from decision_hub.domain.tracker_service import process_tracker_remote

    return process_tracker_remote(tracker_dict, known_sha, github_token)


_TRACKER_LOOP_BUDGET_SECONDS = 480  # 8 min, leaving 2-min buffer before 600s timeout


@app.function(image=crawler_image, secrets=secrets, timeout=600, schedule=modal.Period(seconds=600))
def check_trackers():
    """Poll GitHub repos for skill updates every 10 minutes.

    Loops batch claims until no more trackers are due or the time budget
    is exhausted. Each iteration claims a batch, checks SHAs via GraphQL,
    and fans out changed repos to tracker_process_repo containers.
    Unchanged trackers are near-instant (~1s per 250 repos), so the loop
    can churn through tens of thousands of trackers per tick.

    After the loop, persists one tracker_metrics row with accumulated counters.
    """
    import time

    from loguru import logger

    from decision_hub.domain.tracker_service import check_all_due_trackers
    from decision_hub.logging import setup_logging
    from decision_hub.settings import create_settings

    settings = create_settings()
    setup_logging(settings.log_level)

    start = time.monotonic()
    total_checked = 0
    total_due = 0
    total_unchanged = 0
    total_changed = 0
    total_errored = 0
    total_processed = 0
    total_failed = 0
    total_skipped_rate_limit = 0
    last_github_rate: int | None = None
    iterations = 0

    while time.monotonic() - start < _TRACKER_LOOP_BUDGET_SECONDS:
        result = check_all_due_trackers(settings)
        total_checked += result.checked
        total_due += result.due
        total_unchanged += result.unchanged
        total_changed += result.changed
        total_errored += result.errored
        total_processed += result.processed
        total_failed += result.failed
        total_skipped_rate_limit += result.skipped_rate_limit
        if result.github_rate_remaining is not None:
            last_github_rate = result.github_rate_remaining
        iterations += 1
        if result.checked == 0:
            break

    elapsed = time.monotonic() - start

    # Persist metrics row
    try:
        from decision_hub.infra.database import create_engine, insert_tracker_metrics

        engine = create_engine(settings.database_url)
        with engine.connect() as conn:
            insert_tracker_metrics(
                conn,
                iterations=iterations,
                total_checked=total_checked,
                trackers_due=total_due,
                trackers_unchanged=total_unchanged,
                trackers_changed=total_changed,
                trackers_errored=total_errored,
                trackers_processed=total_processed,
                trackers_failed=total_failed,
                skipped_rate_limit=total_skipped_rate_limit,
                github_rate_remaining=last_github_rate,
                batch_duration_seconds=elapsed,
            )
            conn.commit()
    except Exception:
        logger.opt(exception=True).warning("Failed to persist tracker_metrics row")

    logger.info(
        "check_trackers done iterations={} total_checked={} elapsed={:.1f}s",
        iterations,
        total_checked,
        elapsed,
    )
    print(f"[check_trackers] Checked {total_checked} tracker(s) in {iterations} iteration(s)", flush=True)
