"""Test that fetch_marketplace_skills function is importable and has the right signature."""

import inspect

from decision_hub.infra.database import fetch_marketplace_skills


def test_fetch_marketplace_skills_signature():
    sig = inspect.signature(fetch_marketplace_skills)
    params = list(sig.parameters.keys())
    assert "conn" in params
    assert "limit" in params
