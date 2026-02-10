"""Modal deployment entry point for Decision Hub API."""

import os
from pathlib import Path

import modal

env = os.environ.get("DHUB_ENV", "prod")
suffix = "" if env == "prod" else f"-{env}"
app_name = f"decision-hub{suffix}"

app = modal.App(app_name)

_frontend_dist = Path("../frontend/dist")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .add_local_dir("../shared", remote_path="/tmp/dhub-core", copy=True)
    .run_commands("pip install /tmp/dhub-core")
    .pip_install_from_pyproject("pyproject.toml")
    .add_local_dir("src/decision_hub", remote_path="/root/decision_hub", copy=True)
)

# Extended image for the crawler — adds git for cloning repos
crawler_image = image.apt_install("git")

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
    # Inject MODAL_APP_NAME so the web function can spawn eval tasks
    # in the correct app (the .env file isn't deployed to Modal).
    modal.Secret.from_dict({"MODAL_APP_NAME": app_name}),
]


@app.function(image=image, secrets=secrets, scaledown_window=300, cpu=0.5, memory=256)
@modal.concurrent(max_inputs=100)
@modal.asgi_app(label=f"api{suffix}")
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


@app.function(image=crawler_image, secrets=secrets, timeout=300)
def crawl_process_repo(
    repo_dict: dict,
    bot_user_id: str,
    github_token: str | None = None,
) -> dict:
    """Process a single discovered repo: clone, discover skills, gauntlet, publish.

    Runs on Modal with ephemeral disk and access to DB/S3/Gemini secrets.
    Returns a result dict with status and counts.
    """
    from decision_hub.scripts.github_crawler import process_repo_on_modal

    return process_repo_on_modal(repo_dict, bot_user_id, github_token)
