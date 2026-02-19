"""FastAPI application factory."""

import json as _json
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.types import ASGIApp, Receive, Scope, Send

from decision_hub.api.deps import get_current_user
from decision_hub.infra.database import create_engine
from decision_hub.infra.storage import create_s3_client
from decision_hub.logging import RequestLoggingMiddleware, setup_logging
from decision_hub.settings import create_settings

# Frontend dist directory — populated at deploy time by the build script.
# When the directory exists the app serves the SPA; otherwise API-only mode.
_FRONTEND_DIR = Path("/root/frontend_dist")


def _parse_semver(v: str) -> tuple[int, ...]:
    """Parse '1.2.3' into (1, 2, 3) for comparison."""
    return tuple(int(x) for x in v.split("."))


class CLIVersionMiddleware:
    """Pure ASGI middleware that rejects outdated CLI versions.

    Implemented as a raw ASGI middleware instead of using Starlette's
    ``BaseHTTPMiddleware`` / ``@app.middleware("http")``.  BaseHTTPMiddleware
    wraps the ASGI ``receive`` callable, which deadlocks when a downstream
    endpoint reads a multipart file upload (e.g. ``UploadFile``).  When the
    request hangs long enough to time out, PgBouncer keeps the connection's
    transaction open (``idle in transaction``), and the held row locks block
    every subsequent UPDATE on the same rows — making the problem look like a
    DB issue rather than a middleware one.  Passing ``receive`` through
    unchanged avoids the deadlock entirely.
    """

    def __init__(self, app: ASGIApp, min_version: str) -> None:
        self.app = app
        self.min_version = min_version
        self._min_parsed = _parse_semver(min_version)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if not path.startswith("/v1/"):
            await self.app(scope, receive, send)
            return

        # Extract X-DHub-Client-Version from raw ASGI headers
        client_ver = ""
        for name, value in scope.get("headers", []):
            if name == b"x-dhub-client-version":
                client_ver = value.decode("latin-1")
                break

        # Only enforce version check for CLI requests (those sending the header).
        # Browser / frontend requests don't send the header and should pass through.
        if client_ver and _parse_semver(client_ver) < self._min_parsed:
            body = _json.dumps(
                {
                    "detail": (
                        f"Your CLI version ({client_ver or 'unknown'}) is below the "
                        f"minimum required ({self.min_version}). "
                        "Run 'uv tool install --upgrade dhub-cli' or "
                        "'pip install --upgrade dhub-cli' to update."
                    ),
                }
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 426,
                    "headers": [
                        [b"content-type", b"application/json"],
                        [b"content-length", str(len(body)).encode()],
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Initialises the database engine, S3 client, and registers all routers.
    Write endpoints (publish, delete, keys, orgs, trackers) always require
    a valid JWT — authentication is unconditional.  The ``require_github_org``
    setting is an *authorization* restriction checked at login time, not an
    authentication toggle.

    Returns:
        A fully-configured FastAPI instance.
    """
    settings = create_settings()
    setup_logging(settings.log_level)

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

    # Request logging with correlation IDs — outermost middleware (added first
    # so Starlette wraps it last, ensuring it runs before everything else).
    app.add_middleware(RequestLoggingMiddleware)

    if settings.min_cli_version:
        app.add_middleware(
            CLIVersionMiddleware,
            min_version=settings.min_cli_version,
        )

    @app.get("/cli/latest-version", tags=["cli"])
    def latest_version() -> dict[str, str]:
        """Return the latest published CLI version for upgrade checks."""
        return {"latest_version": settings.latest_cli_version}

    from decision_hub.api.auth_routes import router as auth_router
    from decision_hub.api.keys_routes import router as keys_router
    from decision_hub.api.org_routes import org_public_router, org_router
    from decision_hub.api.registry_routes import public_router as registry_public_router
    from decision_hub.api.registry_routes import router as registry_router
    from decision_hub.api.search_routes import router as search_router
    from decision_hub.api.taxonomy_routes import public_router as taxonomy_public_router
    from decision_hub.api.tracker_routes import router as tracker_router

    # Auth routes are always public (users need them to obtain a token).
    app.include_router(auth_router)

    # Public read-only registry endpoints (skill listing, download, eval
    # reports, audit logs). These are accessible without auth so the
    # frontend can display skills. When private skills are added, visibility
    # filtering will happen at the query layer, not the route layer.
    app.include_router(registry_public_router)
    app.include_router(taxonomy_public_router)
    app.include_router(org_public_router)

    # Always require a valid JWT on write routers.  This is defense-in-depth:
    # each endpoint also declares its own Depends(get_current_user) to inject
    # the User object, so even if a new endpoint forgot the parameter-level
    # dependency, the router-level guard would still reject anonymous requests.
    # Authentication must not depend on whether an authorization setting like
    # require_github_org happens to be populated.
    write_deps: list = [Depends(get_current_user)]

    app.include_router(org_router, dependencies=write_deps)
    app.include_router(registry_router, dependencies=write_deps)
    app.include_router(keys_router, dependencies=write_deps)
    app.include_router(tracker_router, dependencies=write_deps)
    # Search and ask are read-only and should be accessible without auth,
    # like the public registry endpoints.
    app.include_router(search_router)

    # SEO routes (sitemap.xml, robots.txt) — must be registered before the
    # SPA catch-all so these paths are handled by the API, not served as
    # index.html.
    from decision_hub.api.seo_routes import router as seo_router

    app.include_router(seo_router)

    # --- Frontend SPA serving ---
    # If the frontend build was baked into the image, serve it from the
    # same origin.  Static assets (JS/CSS) are served from /assets/ and
    # every other non-API path falls back to index.html for client-side
    # routing.  When _FRONTEND_DIR is absent the app runs in API-only mode.
    _index_html = _FRONTEND_DIR / "index.html"
    if _FRONTEND_DIR.is_dir() and _index_html.is_file():
        app.mount(
            "/assets",
            StaticFiles(directory=_FRONTEND_DIR / "assets"),
            name="frontend-assets",
        )

        @app.get("/vite.svg", include_in_schema=False)
        def favicon():
            return FileResponse(_FRONTEND_DIR / "vite.svg")

        # SPA catch-all: any path not matched by API routes returns index.html
        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str):
            return FileResponse(_index_html)

    logger.info("Decision Hub app ready (log_level={})", settings.log_level)
    return app
