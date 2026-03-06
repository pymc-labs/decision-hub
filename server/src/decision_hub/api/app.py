"""FastAPI application factory."""

import json as _json
from pathlib import Path
from typing import ClassVar

import sqlalchemy as sa
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from starlette.types import ASGIApp, Receive, Scope, Send

from decision_hub.api.deps import get_current_user
from decision_hub.infra.database import create_engine
from decision_hub.infra.storage import create_s3_client
from decision_hub.logging import RequestLoggingMiddleware, setup_logging
from decision_hub.settings import create_settings
from dhub_core.validation import parse_semver as _parse_semver

# Frontend dist directory — populated at deploy time by the build script.
# When the directory exists the app serves the SPA; otherwise API-only mode.
_FRONTEND_DIR = Path("/root/frontend_dist")


class SecurityHeadersMiddleware:
    """Pure ASGI middleware that adds standard security headers to every response.

    Adds:
    - X-Frame-Options: DENY — prevents clickjacking by disallowing iframe embedding
    - X-Content-Type-Options: nosniff — prevents MIME-type sniffing attacks
    - Strict-Transport-Security — enforces HTTPS for 1 year (with subdomains)

    Implemented as raw ASGI to avoid the receive-wrapping deadlock with UploadFile.
    """

    _HEADERS: ClassVar[list[list[bytes]]] = [
        [b"x-frame-options", b"DENY"],
        [b"x-content-type-options", b"nosniff"],
        [b"strict-transport-security", b"max-age=31536000; includeSubDomains"],
    ]

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(self._HEADERS)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


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
        # Malformed version headers are treated as outdated — return 426 so the
        # client upgrades to a version that sends a valid semver header.
        if client_ver:
            try:
                client_parsed = _parse_semver(client_ver)
            except ValueError:
                client_parsed = (0, 0, 0)
        if client_ver and client_parsed < self._min_parsed:
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
    setup_logging(settings.log_level, log_format=settings.log_format)

    engine = create_engine(settings.database_url)

    s3_client = create_s3_client(
        settings.aws_region,
        settings.aws_access_key_id,
        settings.aws_secret_access_key,
        settings.s3_endpoint_url,
    )

    app = FastAPI(title="Decision Hub", version="0.1.0")
    app.state.engine = engine
    app.state.settings = settings
    app.state.s3_client = s3_client

    # In-memory TTL cache for hot read paths (per-container, not shared
    # across Modal replicas).
    from decision_hub.infra.cache import TTLCache

    app.state.cache = TTLCache(default_ttl=60)

    # Request logging with correlation IDs — outermost middleware (added first
    # so Starlette wraps it last, ensuring it runs before everything else).
    app.add_middleware(RequestLoggingMiddleware)

    # Security headers on every response (X-Frame-Options, X-Content-Type-Options,
    # Strict-Transport-Security). Added after logging so headers appear on all
    # responses including error pages and middleware rejections.
    app.add_middleware(SecurityHeadersMiddleware)

    if settings.min_cli_version:
        app.add_middleware(
            CLIVersionMiddleware,
            min_version=settings.min_cli_version,
        )

    @app.get("/cli/latest-version", tags=["cli"])
    def latest_version() -> dict[str, str]:
        """Return the latest published CLI version for upgrade checks."""
        return {"latest_version": settings.latest_cli_version}

    @app.get("/health", tags=["ops"])
    def health_check() -> dict:
        """Verify service and database connectivity.

        Returns HTTP 200 with ``{"status": "ok", "database": "ok"}`` when
        healthy.  Returns HTTP 503 when the database is unreachable.
        """
        try:
            with engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
            db_status = "ok"
        except Exception:
            logger.opt(exception=True).warning("Health check: database unreachable")
            raise HTTPException(
                status_code=503,
                detail={"status": "degraded", "database": "unreachable"},
            ) from None
        return {"status": "ok", "database": db_status}

    from decision_hub.api.auth_routes import router as auth_router
    from decision_hub.api.keys_routes import router as keys_router
    from decision_hub.api.org_routes import org_public_router, org_router
    from decision_hub.api.plugin_routes import public_router as plugin_public_router
    from decision_hub.api.plugin_routes import router as plugin_router
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
    app.include_router(plugin_public_router)
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
    app.include_router(plugin_router, dependencies=write_deps)
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
    try:
        _has_frontend = _FRONTEND_DIR.is_dir() and _index_html.is_file()
    except PermissionError:
        logger.warning("Cannot access frontend directory {}: permission denied, running API-only", _FRONTEND_DIR)
        _has_frontend = False
    if _has_frontend:
        app.mount(
            "/assets",
            StaticFiles(directory=_FRONTEND_DIR / "assets"),
            name="frontend-assets",
        )

        # Root-level static files from frontend/public/ (favicon, OG image,
        # apple-touch-icon, etc.).  Checked inside the SPA catch-all so
        # crawlers and social-media bots get the actual file instead of
        # index.html, while SPA client-side routes still work normally.
        _ROOT_STATIC_FILES = {
            "vite.svg",
            "og-image.png",
            "favicon.ico",
            "favicon-16x16.png",
            "favicon-32x32.png",
            "apple-touch-icon.png",
        }

        # SPA catch-all: any path not matched by API routes returns index.html.
        # Paths under /v1/ are API namespace — return JSON 404 instead of HTML
        # so API clients get a proper error.  Root-level static files are
        # served directly.  Only GET reaches here (Starlette 0.50+ doesn't
        # implicitly add HEAD), so 405 Method Not Allowed is preserved for
        # real endpoints receiving unsupported methods.
        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str):
            if full_path.startswith("v1/") or full_path == "v1":
                raise HTTPException(
                    status_code=404,
                    detail=f"API endpoint not found: /{full_path}",
                )
            # Serve root-level static files directly (e.g. og-image.png,
            # favicon.ico) so social media crawlers get the real file.
            if full_path in _ROOT_STATIC_FILES:
                filepath = _FRONTEND_DIR / full_path
                if filepath.is_file():
                    return FileResponse(filepath)
            return FileResponse(_index_html)

    logger.info("Decision Hub app ready (log_level={})", settings.log_level)
    return app
