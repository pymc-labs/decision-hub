"""Tests for the manifest_path validator on /v1/publish.

manifest_path is a publisher-controlled string that ends up in API
responses and "view on GitHub" URLs. The validator rejects anything that
isn't a clean relative repo path so traversal/garbage values don't get
stored.
"""

import pytest
from fastapi import HTTPException

from decision_hub.api.registry_routes import _validate_manifest_path


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "skills/foo/SKILL.md",
        "a.b-c_d/e",
        "single-file.md",
    ],
)
def test_accepts_safe_paths(value: object) -> None:
    # None and "" are valid (no path supplied).
    result = _validate_manifest_path(value)
    if not value:
        assert result is None
    else:
        assert result == value


@pytest.mark.parametrize(
    "value",
    [
        "../etc/passwd",
        "skills/../../etc/passwd",
        "/absolute/path",
        "\\windows\\path",
        "skills/./hidden",
        "skills/../foo",
        "has space/skill",
        "weird?chars",
        "null\0byte",
    ],
)
def test_rejects_traversal_and_unsafe_chars(value: str) -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_manifest_path(value)
    assert exc.value.status_code == 422


def test_rejects_excessive_length() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_manifest_path("a" * 1024)
    assert exc.value.status_code == 422


def test_rejects_non_string() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_manifest_path(123)
    assert exc.value.status_code == 422
