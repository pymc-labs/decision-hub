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
    """fetch_org_metadata fetches org profile from GitHub API."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        respx.get("https://api.github.com/orgs/pymc-labs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "avatar_url": "https://avatars.githubusercontent.com/u/123",
                    "email": "info@pymc-labs.com",
                    "description": "Bayesian stats",
                    "blog": "https://pymc-labs.com",
                    "name": "PyMC Labs",
                },
            )
        )

        result = await fetch_org_metadata("gh-token", "pymc-labs")

        assert result == {
            "avatar_url": "https://avatars.githubusercontent.com/u/123",
            "email": "info@pymc-labs.com",
            "description": "Bayesian stats",
            "blog": "https://pymc-labs.com",
        }

    @respx.mock
    @pytest.mark.asyncio
    async def test_missing_fields_default_to_none(self) -> None:
        respx.get("https://api.github.com/orgs/minimal-org").mock(
            return_value=httpx.Response(
                200,
                json={"login": "minimal-org"},
            )
        )

        result = await fetch_org_metadata("gh-token", "minimal-org")

        assert result == {
            "avatar_url": None,
            "email": None,
            "description": None,
            "blog": None,
        }

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_on_error(self) -> None:
        respx.get("https://api.github.com/orgs/bad-org").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        with pytest.raises(httpx.HTTPStatusError):
            await fetch_org_metadata("gh-token", "bad-org")


class TestFetchUserMetadata:
    """fetch_user_metadata fetches user profile and maps bio -> description."""

    @respx.mock
    @pytest.mark.asyncio
    async def test_happy_path_maps_bio_to_description(self) -> None:
        respx.get("https://api.github.com/users/alice").mock(
            return_value=httpx.Response(
                200,
                json={
                    "avatar_url": "https://avatars.githubusercontent.com/u/456",
                    "email": "alice@example.com",
                    "bio": "I do cool stuff",
                    "blog": "https://alice.dev",
                    "login": "alice",
                },
            )
        )

        result = await fetch_user_metadata("gh-token", "alice")

        assert result == {
            "avatar_url": "https://avatars.githubusercontent.com/u/456",
            "email": "alice@example.com",
            "description": "I do cool stuff",
            "blog": "https://alice.dev",
        }

    @respx.mock
    @pytest.mark.asyncio
    async def test_missing_fields_default_to_none(self) -> None:
        respx.get("https://api.github.com/users/minimal").mock(
            return_value=httpx.Response(
                200,
                json={"login": "minimal"},
            )
        )

        result = await fetch_user_metadata("gh-token", "minimal")

        assert result == {
            "avatar_url": None,
            "email": None,
            "description": None,
            "blog": None,
        }

    @respx.mock
    @pytest.mark.asyncio
    async def test_raises_on_error(self) -> None:
        respx.get("https://api.github.com/users/ghost").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )

        with pytest.raises(httpx.HTTPStatusError):
            await fetch_user_metadata("gh-token", "ghost")
