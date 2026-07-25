"""Tests for decision_hub.infra.github -- GitHub API helpers."""

import httpx
import pytest
import respx

from decision_hub.infra.github import (
    _GITHUB_TIMEOUT,
    _parse_next_link,
    check_org_membership,
    fetch_org_metadata,
    fetch_user_metadata,
    list_user_orgs,
)


class TestGithubTimeoutConstant:
    """Every AsyncClient in this module must have an explicit timeout.

    Without one, a stuck TCP connection would pin a FastAPI worker
    indefinitely; the constant is the single knob that fixes that.
    """

    def test_timeout_is_finite(self) -> None:
        assert _GITHUB_TIMEOUT.read is not None
        assert _GITHUB_TIMEOUT.connect is not None


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


class TestCheckOrgMembership:
    """check_org_membership must distinguish "not a member" from "GitHub broke".

    Regression: the previous implementation silently returned False for every
    non-204 status. A 500 during a GitHub incident then locked every real
    member out of login as if they'd been kicked from the org.
    """

    @respx.mock
    @pytest.mark.asyncio
    async def test_204_is_member(self) -> None:
        respx.get("https://api.github.com/orgs/acme/members/alice").mock(return_value=httpx.Response(204))
        assert await check_org_membership("gh-token", "acme", "alice") is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_404_is_not_member(self) -> None:
        respx.get("https://api.github.com/orgs/acme/members/bob").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        assert await check_org_membership("gh-token", "acme", "bob") is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_302_is_not_member(self) -> None:
        # GitHub returns 302 when the caller can't see the membership list
        # (public-only membership + non-member caller).
        respx.get("https://api.github.com/orgs/acme/members/carol").mock(
            return_value=httpx.Response(302, headers={"Location": "https://api.github.com"})
        )
        assert await check_org_membership("gh-token", "acme", "carol") is False

    @respx.mock
    @pytest.mark.asyncio
    async def test_500_raises_instead_of_denying(self) -> None:
        """A GitHub 500 must surface, not silently return False."""
        respx.get("https://api.github.com/orgs/acme/members/dave").mock(
            return_value=httpx.Response(500, json={"message": "Server Error"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            await check_org_membership("gh-token", "acme", "dave")

    @respx.mock
    @pytest.mark.asyncio
    async def test_403_raises(self) -> None:
        """403 (revoked token / rate-limited) is not a definitive answer either."""
        respx.get("https://api.github.com/orgs/acme/members/eve").mock(
            return_value=httpx.Response(403, json={"message": "Forbidden"})
        )
        with pytest.raises(httpx.HTTPStatusError):
            await check_org_membership("gh-token", "acme", "eve")

    @respx.mock
    @pytest.mark.asyncio
    async def test_transport_error_propagates(self) -> None:
        """Network-level errors must reach the caller, not be swallowed."""
        respx.get("https://api.github.com/orgs/acme/members/frank").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        with pytest.raises(httpx.HTTPError):
            await check_org_membership("gh-token", "acme", "frank")
