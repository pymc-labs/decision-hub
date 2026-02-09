"""Centralized logging configuration using loguru.

Call ``setup_logging()`` once at application startup (in ``create_app()``
or at the top of a Modal function) to configure the loguru sink and
intercept stdlib ``logging`` so third-party libraries (uvicorn, sqlalchemy,
httpx) route through the same pipeline.
"""

import logging
import sys
import time
import uuid

from loguru import logger
from starlette.types import ASGIApp, Receive, Scope, Send


class _InterceptHandler(logging.Handler):
    """Bridge stdlib logging → loguru.

    Installed as the root handler so that any library using
    ``logging.getLogger(...)`` emits through loguru with the correct
    caller depth and level.
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Map stdlib level to loguru level name
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find the caller frame that originated the log call.
        # Start at depth=2 to skip emit() and loguru's internal log() frame.
        frame, depth = logging.currentframe(), 2
        while frame is not None:
            if frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1
                continue
            break

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def _format_record(record: dict) -> str:
    """Build the log format string, including request_id when bound."""
    # Base format
    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
    )
    # Include request_id when present (bound via contextualize)
    if record["extra"].get("request_id"):
        fmt += "<yellow>{extra[request_id]}</yellow> | "
    fmt += (
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>\n"
    )
    if record["exception"]:
        fmt += "{exception}"
    return fmt


def setup_logging(level: str = "INFO") -> None:
    """Configure loguru as the single logging sink for the application.

    - Removes the default loguru handler.
    - Adds a stderr handler with a human-readable format that includes
      timestamp, level, module, function, line, and an optional request_id.
    - Intercepts stdlib ``logging`` so libraries like uvicorn and
      sqlalchemy also route through loguru.

    Args:
        level: Minimum log level (DEBUG, INFO, WARNING, ERROR).
    """
    # Remove default loguru handler
    logger.remove()

    # Add a single stderr handler. Uses a callable format so that
    # the request_id column only appears when a request context is active.
    logger.add(
        sys.stderr,
        level=level.upper(),
        format=_format_record,
        backtrace=True,
        diagnose=False,  # disable variable inspection in prod for safety
    )

    # Intercept stdlib logging
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)


class RequestLoggingMiddleware:
    """Pure ASGI middleware that logs every HTTP request with timing.

    Generates a short request ID, binds it to loguru's context for the
    duration of the request, and emits a single summary line when the
    response completes.  The same request ID appears on every log line
    emitted during that request, making it easy to correlate.

    Implemented as raw ASGI (not BaseHTTPMiddleware) to avoid the
    receive-wrapping deadlock with UploadFile endpoints.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex[:8]
        method = scope.get("method", "?")
        path = scope.get("path", "/")

        # Extract username from headers if present (set by auth)
        user = ""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                # Don't log the token, just note auth is present
                user = "(authed)"
                break

        status_code = 0
        start = time.perf_counter()

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        with logger.contextualize(request_id=request_id):
            logger.info("{} {} {}", method, path, user)
            try:
                await self.app(scope, receive, send_wrapper)
            except Exception:
                status_code = 500
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                lvl = "WARNING" if status_code >= 400 else "INFO"
                logger.log(lvl, "{} {} → {} ({:.0f}ms)", method, path, status_code, duration_ms)
