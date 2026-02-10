"""Tests for decision_hub.infra.github -- GitHub API helpers."""

import httpx
import pytest
import respx

from decision_hub.infra.github import _parse_next_link, list_user_orgs


class TestParseNextLink:
    """_parse_next_link extracts the 'next' URL from a GitHub Link header."""

    def test_extracts_next_url(self) -> None:
        header = (
            '<https://api.github.com/user/orgs?page=2>; rel="next", '
            '<https://api.github.com/user/orgs?page=5>; rel="last"'
        )
        assert _parse_next_link(header) == "https://api.github.com/user/orgs?page=2"

    def test_returns_none_when_no_next(self) -> None:
        header = '<https://api.github.com/user/orgs?page=1>; rel="prev"'
        assert _parse_next_link(header) is None

    def test_returns_none_for_empty_string(self) -> None:
        assert _parse_next_link("") is None

    def test_handles_next_only(self) -> None:
        header = '<https://api.github.com/user/orgs?page=3>; rel="next"'
        assert _parse_next_link(header) == "https://api.github.com/user/orgs?page=3"


class TestListUserOrgs:
    """list_user_orgs fetches all user orgs with pagination."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_single_page(self) -> None:
        respx.get("https://api.github.com/user/orgs?per_page=100").mock(
            return_value=httpx.Response(
                200,
                json=[{"login": "org-a"}, {"login": "org-b"}],
            )
        )

        result = await list_user_orgs("gh-token-abc")

        assert len(result) == 2
        assert result[0]["login"] == "org-a"
        assert result[1]["login"] == "org-b"

    @respx.mock
    @pytest.mark.asyncio
    async def test_multiple_pages(self) -> None:
        respx.get("https://api.github.com/user/orgs?per_page=100").mock(
            return_value=httpx.Response(
                200,
                json=[{"login": "org-a"}],
                headers={"Link": '<https://api.github.com/user/orgs?per_page=100&page=2>; rel="next"'},
            )
        )
        respx.get("https://api.github.com/user/orgs?per_page=100&page=2").mock(
            return_value=httpx.Response(
                200,
                json=[{"login": "org-b"}],
            )
        )

        result = await list_user_orgs("gh-token-abc")

        assert len(result) == 2
        assert [o["login"] for o in result] == ["org-a", "org-b"]

    @respx.mock
    @pytest.mark.asyncio
    async def test_empty_orgs(self) -> None:
        respx.get("https://api.github.com/user/orgs?per_page=100").mock(return_value=httpx.Response(200, json=[]))

        result = await list_user_orgs("gh-token-abc")

        assert result == []
