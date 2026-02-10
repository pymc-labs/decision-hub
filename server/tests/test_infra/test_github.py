"""Tests for decision_hub.infra.github -- GitHub API helpers."""

import httpx
import pytest
import respx

from decision_hub.infra.github import (
    _parse_next_link,
    fetch_org_metadata,
    fetch_user_metadata,
    list_user_orgs,
)


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


class TestFetchOrgMetadata:
    """fetch_org_metadata extracts profile fields from the GitHub org API."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_metadata(self) -> None:
        respx.get("https://api.github.com/orgs/pymc-labs").mock(
            return_value=httpx.Response(200, json={
                "login": "pymc-labs",
                "avatar_url": "https://avatars.githubusercontent.com/u/123",
                "email": "info@pymc-labs.com",
                "description": "Bayesian modeling",
                "blog": "https://pymc-labs.com",
            })
        )

        meta = await fetch_org_metadata("token", "pymc-labs")

        assert meta["avatar_url"] == "https://avatars.githubusercontent.com/u/123"
        assert meta["email"] == "info@pymc-labs.com"
        assert meta["description"] == "Bayesian modeling"
        assert meta["blog"] == "https://pymc-labs.com"

    @respx.mock
    @pytest.mark.asyncio
    async def test_empty_values_become_none(self) -> None:
        respx.get("https://api.github.com/orgs/empty-org").mock(
            return_value=httpx.Response(200, json={
                "login": "empty-org",
                "avatar_url": "",
                "email": "",
                "description": "",
                "blog": "",
            })
        )

        meta = await fetch_org_metadata("token", "empty-org")

        assert meta["avatar_url"] is None
        assert meta["email"] is None
        assert meta["description"] is None
        assert meta["blog"] is None


class TestFetchUserMetadata:
    """fetch_user_metadata extracts profile fields from the GitHub user API."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_returns_metadata_with_bio_as_description(self) -> None:
        respx.get("https://api.github.com/users/alice").mock(
            return_value=httpx.Response(200, json={
                "login": "alice",
                "avatar_url": "https://avatars.githubusercontent.com/u/456",
                "email": "alice@example.com",
                "bio": "Data scientist",
                "blog": "https://alice.dev",
            })
        )

        meta = await fetch_user_metadata("token", "alice")

        assert meta["avatar_url"] == "https://avatars.githubusercontent.com/u/456"
        assert meta["email"] == "alice@example.com"
        assert meta["description"] == "Data scientist"
        assert meta["blog"] == "https://alice.dev"
