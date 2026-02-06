"""Modal deployment entry point for Decision Hub API."""

import os

import modal

env = os.environ.get("DHUB_ENV", "prod")
suffix = "" if env == "prod" else f"-{env}"

app = modal.App(f"decision-hub{suffix}")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_pyproject("pyproject.toml")
    .add_local_dir("src/decision_hub", remote_path="/root/decision_hub")
)


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name(f"decision-hub-db{suffix}"),
        modal.Secret.from_name(f"decision-hub-secrets{suffix}"),
        modal.Secret.from_name(f"decision-hub-aws{suffix}"),
    ],
    scaledown_window=300,
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app(label=f"api{suffix}")
def web():
    """Serve the Decision Hub FastAPI application."""
    from decision_hub.api.app import create_app

    return create_app()
