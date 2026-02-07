"""Modal deployment entry point for Decision Hub API."""

import os

import modal

env = os.environ.get("DHUB_ENV", "prod")
suffix = "" if env == "prod" else f"-{env}"
app_name = f"decision-hub{suffix}"

app = modal.App(app_name)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_pyproject("pyproject.toml")
    .add_local_dir("src/decision_hub", remote_path="/root/decision_hub")
)

secrets = [
    modal.Secret.from_name(f"decision-hub-db{suffix}"),
    modal.Secret.from_name(f"decision-hub-secrets{suffix}"),
    modal.Secret.from_name(f"decision-hub-aws{suffix}"),
    # Inject MODAL_APP_NAME so the web function can spawn eval tasks
    # in the correct app (the .env file isn't deployed to Modal).
    modal.Secret.from_dict({"MODAL_APP_NAME": app_name}),
]


@app.function(image=image, secrets=secrets, scaledown_window=300)
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
    skill_zip: bytes,
    org_slug: str,
    skill_name: str,
    user_id: str,
):
    """Run agent evaluation in its own Modal container.

    Spawned asynchronously from the publish endpoint so the eval
    has its own lifecycle and doesn't get killed when the web
    container scales down.
    """
    import sys
    from uuid import UUID

    from decision_hub.api.registry_routes import _run_assessment_background
    from decision_hub.models import EvalCase, EvalConfig
    from decision_hub.settings import create_settings

    print(f"[run_eval_task] Starting eval for {org_slug}/{skill_name} "
          f"version={version_id} agent={eval_agent} cases={len(eval_cases_dicts)}",
          flush=True)

    settings = create_settings()
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

    print(f"[run_eval_task] Settings loaded, calling _run_assessment_background",
          flush=True)

    _run_assessment_background(
        version_id=UUID(version_id),
        eval_config=config,
        eval_cases=cases,
        skill_zip=skill_zip,
        org_slug=org_slug,
        skill_name=skill_name,
        settings=settings,
        user_id=UUID(user_id),
    )

    print(f"[run_eval_task] Completed for {org_slug}/{skill_name}", flush=True)
