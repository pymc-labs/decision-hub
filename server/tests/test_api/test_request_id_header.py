"""Verify ``RequestLoggingMiddleware`` echoes ``X-Request-ID`` on responses.

The middleware already generates an 8-char request id per request and binds
it to the loguru context — see ``decision_hub.logging.RequestLoggingMiddleware``.
Echoing the id on the response is what lets clients quote it in bug reports
and lets ops correlate "the user got error X at time T" with server logs.
"""

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from decision_hub.logging import RequestLoggingMiddleware

_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{8}$")


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    return app


def test_request_id_header_present_on_success() -> None:
    """Every 2xx response carries an ``X-Request-ID`` header."""
    client = TestClient(_make_app())
    resp = client.get("/ping")

    assert resp.status_code == 200
    request_id = resp.headers.get("x-request-id")
    assert request_id is not None
    assert _REQUEST_ID_RE.match(request_id), f"unexpected request-id shape: {request_id!r}"


def test_request_id_header_present_on_404() -> None:
    """Error responses also carry an ``X-Request-ID`` header.

    This is the case that matters most for support — a user reports "I got
    a 404", and the request id makes the corresponding log line findable.
    """
    client = TestClient(_make_app())
    resp = client.get("/does-not-exist")

    assert resp.status_code == 404
    assert _REQUEST_ID_RE.match(resp.headers.get("x-request-id", ""))


def test_request_id_is_unique_per_request() -> None:
    """Two concurrent requests get two different request ids."""
    client = TestClient(_make_app())
    a = client.get("/ping").headers["x-request-id"]
    b = client.get("/ping").headers["x-request-id"]
    assert a != b
