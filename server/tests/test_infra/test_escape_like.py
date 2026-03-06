"""Tests for _escape_like SQL wildcard escaping."""

import pytest

from decision_hub.infra.database import _escape_like


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("hello", "hello"),
        ("100%", "100\\%"),
        ("under_score", "under\\_score"),
        ("%admin%", "\\%admin\\%"),
        ("back\\slash", "back\\\\slash"),
        ("a%b_c\\d", "a\\%b\\_c\\\\d"),
        ("", ""),
    ],
    ids=[
        "plain-text-unchanged",
        "percent-escaped",
        "underscore-escaped",
        "multiple-percents",
        "backslash-escaped",
        "all-special-chars",
        "empty-string",
    ],
)
def test_escape_like(raw: str, expected: str) -> None:
    assert _escape_like(raw) == expected
