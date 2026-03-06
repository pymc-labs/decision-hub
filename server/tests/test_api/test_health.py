"""Tests for the GET /health endpoint."""

from unittest.mock import MagicMock

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _create_health_app(engine: MagicMock) -> FastAPI:
    """Create a minimal FastAPI app with the health endpoint wired up."""
    app = FastAPI()
    app.state.engine = engine

    @app.get("/health")
    def health_check() -> dict:
        try:
            with engine.connect() as conn:
                conn.execute(sa.text("SELECT 1"))
            db_status = "ok"
        except Exception:
            raise HTTPException(
                status_code=503,
                detail={"status": "degraded", "database": "unreachable"},
            ) from None
        return {"status": "ok", "database": db_status}

    return app


class TestHealthEndpoint:
    def test_healthy_when_db_reachable(self):
        """GET /health returns 200 with ok status when DB responds."""
        engine = MagicMock()
        app = _create_health_app(engine)
        client = TestClient(app)

        resp = client.get("/health")

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"

    def test_degraded_when_db_unreachable(self):
        """GET /health returns 503 when DB connection fails."""
        engine = MagicMock()
        engine.connect.side_effect = Exception("connection refused")
        app = _create_health_app(engine)
        client = TestClient(app)

        resp = client.get("/health")

        assert resp.status_code == 503
        body = resp.json()
        assert body["detail"]["status"] == "degraded"
        assert body["detail"]["database"] == "unreachable"
