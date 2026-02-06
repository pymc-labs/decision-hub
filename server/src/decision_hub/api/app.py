"""FastAPI application factory."""

from fastapi import Depends, FastAPI

from decision_hub.api.deps import get_current_user
from decision_hub.infra.database import create_engine
from decision_hub.infra.storage import create_s3_client
from decision_hub.settings import Settings


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Initialises the database engine, S3 client, and registers all routers.
    When ``require_github_org`` is set, all non-auth routes require a valid
    JWT (enforced via an app-wide dependency).

    Returns:
        A fully-configured FastAPI instance.
    """
    settings = Settings()

    engine = create_engine(settings.database_url)

    s3_client = create_s3_client(
        settings.aws_region,
        settings.aws_access_key_id,
        settings.aws_secret_access_key,
    )

    app = FastAPI(title="Decision Hub", version="0.1.0")
    app.state.engine = engine
    app.state.settings = settings
    app.state.s3_client = s3_client

    from decision_hub.api.auth_routes import router as auth_router
    from decision_hub.api.keys_routes import router as keys_router
    from decision_hub.api.org_routes import invite_router, org_router
    from decision_hub.api.registry_routes import router as registry_router
    from decision_hub.api.search_routes import router as search_router

    # Auth routes are always public (users need them to obtain a token).
    app.include_router(auth_router)

    # When an org restriction is active, require a valid JWT on every
    # non-auth route. This locks down the otherwise-public endpoints
    # (search, skill listing, resolve) without touching each route.
    global_deps: list = []
    if settings.require_github_org:
        global_deps = [Depends(get_current_user)]

    app.include_router(org_router, dependencies=global_deps)
    app.include_router(invite_router, dependencies=global_deps)
    app.include_router(registry_router, dependencies=global_deps)
    app.include_router(keys_router, dependencies=global_deps)
    app.include_router(search_router, dependencies=global_deps)

    return app
