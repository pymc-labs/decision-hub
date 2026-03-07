"""Centralized logging configuration using loguru.

Call ``setup_logging()`` once at application startup (in ``create_app()``
or at the top of a Modal function) to configure the loguru sink and
intercept stdlib ``logging`` so third-party libraries (uvicorn, sqlalchemy,
httpx) route through the same pipeline.
"""

import json
import logging
import re
import sys
import time
import traceback
import uuid

from loguru import logger
from starlette.types import ASGIApp, Receive, Scope, Send

_SENSITIVE_URL_PARAM_RE = re.compile(r"(\bkey=)[^&\s\"']+")


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
                frame = frame.f_back  # type: ignore[assignment]  # f_back is Optional; loop handles None
                depth += 1
                continue
            break

        msg = _SENSITIVE_URL_PARAM_RE.sub(r"\1[REDACTED]", record.getMessage())
        logger.opt(depth=depth, exception=record.exc_info).log(level, msg)


def _format_record(record: dict) -> str:
    """Build the log format string, including request_id when bound."""
    # Base format
    fmt = "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | "
    # Include request_id when present (bound via contextualize)
    if record["extra"].get("request_id"):
        fmt += "<yellow>{extra[request_id]}</yellow> | "
    fmt += "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>\n"
    if record["exception"]:
        fmt += "{exception}"
    return fmt


def _json_sink(message) -> None:
    """Serialize each log record as a single JSON line to stderr."""
    record = message.record
    extra = record["extra"]
    entry: dict = {
        "timestamp": record["time"].isoformat(),
        "level": record["level"].name,
        "message": record["message"],
        "logger": record["name"],
        "function": record["function"],
        "line": record["line"],
    }
    # Include bound context fields (request_id, user, org_slug, etc.)
    for key in ("request_id", "user", "org_slug", "skill_name", "response_size"):
        if key in extra:
            entry[key] = extra[key]
    if record["exception"]:
        exc_type, exc_value, exc_tb = record["exception"]
        entry["exception"] = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    sys.stderr.write(json.dumps(entry, default=str) + "\n")
    sys.stderr.flush()


def setup_logging(level: str = "INFO", log_format: str = "text") -> None:
    """Configure loguru as the single logging sink for the application.

    - Removes the default loguru handler.
    - Adds a stderr handler with either human-readable ("text") or
      structured ("json") format.
    - Intercepts stdlib ``logging`` so libraries like uvicorn and
      sqlalchemy also route through loguru.

    Args:
        level: Minimum log level (DEBUG, INFO, WARNING, ERROR).
        log_format: "text" for human-readable or "json" for structured JSON lines.
    """
    # Remove default loguru handler
    logger.remove()

    if log_format.lower() == "json":
        logger.add(
            _json_sink,
            level=level.upper(),
            format="{message}",
            backtrace=True,
            diagnose=False,
        )
    else:
        # Human-readable format. Uses a callable format so that
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


# Pattern to extract org_slug and skill_name from common API paths:
# /v1/skills/{org}/{skill}/...  or  /v1/orgs/{org}/skills/{skill}/...
_PATH_CONTEXT_RE = re.compile(
    r"/v1/skills/(?P<org>[^/]+)/(?P<skill>[^/]+)"
    r"|"
    r"/v1/orgs/(?P<org2>[^/]+)/skills/(?P<skill2>[^/]+)"
)


class RequestLoggingMiddleware:
    """Pure ASGI middleware that logs every HTTP request with timing.

    Generates a short request ID, binds it to loguru's context for the
    duration of the request, and emits a single summary line when the
    response completes.  The same request ID appears on every log line
    emitted during that request, making it easy to correlate.

    Enhanced context:
    - ``user``: username extracted from JWT (without logging the token)
    - ``org_slug`` / ``skill_name``: parsed from the URL path
    - ``response_size``: total response body bytes

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

        # Extract username from JWT payload if present.
        # The JWT is a base64url-encoded JSON with a "username" claim.
        user = ""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                user = _extract_username_from_jwt(value.decode("latin-1"))
                break

        # Extract org/skill context from URL path
        org_slug = ""
        skill_name = ""
        m = _PATH_CONTEXT_RE.search(path)
        if m:
            # Two alternative patterns: "org"/"skill" or "org2"/"skill2"
            org_slug = m.group("org") or m.group("org2") or ""
            skill_name = m.group("skill") or m.group("skill2") or ""

        status_code = 0
        response_size = 0
        start = time.perf_counter()

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code, response_size
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body:
                    response_size += len(body)
            await send(message)

        ctx: dict = {"request_id": request_id}
        if user:
            ctx["user"] = user
        if org_slug:
            ctx["org_slug"] = org_slug
        if skill_name:
            ctx["skill_name"] = skill_name

        with logger.contextualize(**ctx):
            logger.info("{} {} {}", method, path, user)
            try:
                await self.app(scope, receive, send_wrapper)
            except Exception:
                status_code = 500
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                lvl = "WARNING" if status_code >= 400 else "INFO"
                logger.bind(response_size=response_size).log(
                    lvl,
                    "{} {} → {} ({:.0f}ms, {}B)",
                    method,
                    path,
                    status_code,
                    duration_ms,
                    response_size,
                )


def _extract_username_from_jwt(auth_header: str) -> str:
    """Extract the username from a Bearer JWT without verifying it.

    This is only used for logging context — actual auth verification
    happens in the dependency layer. We decode the payload segment
    (base64url) to read the ``username`` claim. Returns empty string
    on any failure.
    """
    import base64

    try:
        if not auth_header.startswith("Bearer "):
            return ""
        token = auth_header[7:]
        parts = token.split(".")
        if len(parts) != 3:
            return ""
        # Pad base64url payload
        payload_b64 = parts[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("username", "")
    except Exception:
        return ""
