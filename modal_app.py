"""Modal deployment entry point for Decision Hub API."""

import modal

app = modal.App("decision-hub")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install_from_pyproject("pyproject.toml")
)


@app.function(
    image=image,
    secrets=[
        modal.Secret.from_name("decision-hub-db"),
        modal.Secret.from_name("decision-hub-secrets"),
        modal.Secret.from_name("decision-hub-aws"),
    ],
    scaledown_window=300,
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app(label="api")
def web():
    """Serve the Decision Hub FastAPI application."""
    from decision_hub.api.app import create_app

    return create_app()
