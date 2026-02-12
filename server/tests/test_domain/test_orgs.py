"""Tests for decision_hub.domain.orgs -- organisation validation and sync logic."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from decision_hub.domain.orgs import sync_org_github_metadata, sync_user_orgs, validate_org_slug, validate_role

# ---------------------------------------------------------------------------
# validate_org_slug
# ---------------------------------------------------------------------------


class TestValidateOrgSlug:
    """Slug validation: lowercase alphanumeric + hyphens, 1-64 chars."""

    @pytest.mark.parametrize(
        "slug",
        [
            "a",  # single char
            "my-org",  # typical slug
            "org123",  # numbers allowed
            "a" * 64,  # max length
            "abc-def-ghi",  # multiple hyphens
            "0-start-with-digit",  # digits at start
        ],
    )
    def test_valid_slugs(self, slug: str) -> None:
        assert validate_org_slug(slug) == slug

    @pytest.mark.parametrize(
        "slug,reason",
        [
            ("", "empty string"),
            ("a" * 65, "too long (65 chars)"),
            ("-starts-with-hyphen", "leading hyphen"),
            ("ends-with-hyphen-", "trailing hyphen"),
            ("UpperCase", "uppercase letters"),
            ("has space", "contains space"),
            ("special!chars", "special characters"),
            ("under_score", "underscore not allowed"),
        ],
    )
    def test_invalid_slugs(self, slug: str, reason: str) -> None:
        with pytest.raises(ValueError):
            validate_org_slug(slug)


# ---------------------------------------------------------------------------
# validate_role
# ---------------------------------------------------------------------------


class TestValidateRole:
    @pytest.mark.parametrize("role", ["owner", "admin", "member"])
    def test_valid_roles(self, role: str) -> None:
        assert validate_role(role) == role

    @pytest.mark.parametrize(
        "role",
        ["superadmin", "viewer", "", "Owner", "ADMIN"],
    )
    def test_invalid_roles(self, role: str) -> None:
        with pytest.raises(ValueError):
            validate_role(role)


# ---------------------------------------------------------------------------
# sync_user_orgs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeOrg:
    id: UUID
    slug: str
    owner_id: UUID


@dataclass(frozen=True)
class FakeOrgMember:
    org_id: UUID
    user_id: UUID
    role: str


class TestSyncUserOrgs:
    """sync_user_orgs should create orgs/memberships as needed."""

    def _setup_mocks(self):
        """Return patchers for the four DB functions used by sync_user_orgs."""
        created_orgs: dict[str, FakeOrg] = {}
        created_members: list[tuple[UUID, UUID, str]] = []

        def find_org(c, slug):
            return created_orgs.get(slug)

        def insert_org(c, slug, owner_id, **kwargs):
            org = FakeOrg(id=uuid4(), slug=slug, owner_id=owner_id)
            created_orgs[slug] = org
            return org

        def find_member(c, org_id, uid):
            return None

        def insert_member(c, org_id, uid, role):
            created_members.append((org_id, uid, role))
            return FakeOrgMember(org_id=org_id, user_id=uid, role=role)

        return created_orgs, created_members, find_org, insert_org, find_member, insert_member

    @patch("decision_hub.infra.database.insert_org_member")
    @patch("decision_hub.infra.database.find_org_member")
    @patch("decision_hub.infra.database.insert_organization")
    @patch("decision_hub.infra.database.find_org_by_slug")
    def test_creates_personal_namespace(
        self, mock_find_org, mock_insert_org, mock_find_member, mock_insert_member
    ) -> None:
        """Should always create the personal namespace with 'owner' role."""
        conn = MagicMock()
        user_id = uuid4()
        created_orgs: dict[str, FakeOrg] = {}

        def find_org_side(c, slug):
            return created_orgs.get(slug)

        def insert_org_side(c, slug, owner_id, **kwargs):
            org = FakeOrg(id=uuid4(), slug=slug, owner_id=owner_id)
            created_orgs[slug] = org
            return org

        mock_find_org.side_effect = find_org_side
        mock_insert_org.side_effect = insert_org_side
        mock_find_member.return_value = None
        mock_insert_member.return_value = FakeOrgMember(org_id=uuid4(), user_id=user_id, role="owner")

        result = sync_user_orgs(conn, user_id, [], "Alice")

        assert "alice" in result
        assert "alice" in created_orgs
        # Personal namespace created as owner
        mock_insert_member.assert_called()
        first_call = mock_insert_member.call_args_list[0]
        assert first_call[0][3] == "owner"

    @patch("decision_hub.infra.database.insert_org_member")
    @patch("decision_hub.infra.database.find_org_member")
    @patch("decision_hub.infra.database.insert_organization")
    @patch("decision_hub.infra.database.find_org_by_slug")
    def test_creates_github_orgs(self, mock_find_org, mock_insert_org, mock_find_member, mock_insert_member) -> None:
        """Should create GitHub orgs and add user as member."""
        conn = MagicMock()
        user_id = uuid4()
        created_orgs: dict[str, FakeOrg] = {}

        def find_org_side(c, slug):
            return created_orgs.get(slug)

        def insert_org_side(c, slug, owner_id, **kwargs):
            org = FakeOrg(id=uuid4(), slug=slug, owner_id=owner_id)
            created_orgs[slug] = org
            return org

        mock_find_org.side_effect = find_org_side
        mock_insert_org.side_effect = insert_org_side
        mock_find_member.return_value = None
        mock_insert_member.return_value = FakeOrgMember(org_id=uuid4(), user_id=user_id, role="owner")

        result = sync_user_orgs(conn, user_id, ["pymc-labs", "cool-org"], "testuser")

        assert result == ["cool-org", "pymc-labs", "testuser"]
        assert len(created_orgs) == 3

    @patch("decision_hub.infra.database.insert_org_member")
    @patch("decision_hub.infra.database.find_org_member")
    @patch("decision_hub.infra.database.insert_organization")
    @patch("decision_hub.infra.database.find_org_by_slug")
    def test_adds_member_to_existing_org(
        self, mock_find_org, mock_insert_org, mock_find_member, mock_insert_member
    ) -> None:
        """Should add user as member to an org that already exists."""
        conn = MagicMock()
        user_id = uuid4()
        existing_org = FakeOrg(id=uuid4(), slug="pymc-labs", owner_id=uuid4())

        def find_org_side(c, slug):
            if slug == "pymc-labs":
                return existing_org
            return None

        def insert_org_side(c, slug, owner_id, **kwargs):
            return FakeOrg(id=uuid4(), slug=slug, owner_id=owner_id)

        mock_find_org.side_effect = find_org_side
        mock_insert_org.side_effect = insert_org_side
        mock_find_member.return_value = None
        mock_insert_member.return_value = FakeOrgMember(org_id=uuid4(), user_id=user_id, role="member")

        result = sync_user_orgs(conn, user_id, ["pymc-labs"], "testuser")

        assert "pymc-labs" in result
        # Should add as "member" (not "owner") for an existing org
        member_calls = [c for c in mock_insert_member.call_args_list if c[0][1] == existing_org.id]
        assert any(c[0][3] == "member" for c in member_calls)

    @patch("decision_hub.infra.database.insert_org_member")
    @patch("decision_hub.infra.database.find_org_member")
    @patch("decision_hub.infra.database.insert_organization")
    @patch("decision_hub.infra.database.find_org_by_slug")
    def test_noop_for_existing_member(
        self, mock_find_org, mock_insert_org, mock_find_member, mock_insert_member
    ) -> None:
        """Should not create duplicate membership."""
        conn = MagicMock()
        user_id = uuid4()
        existing_org = FakeOrg(id=uuid4(), slug="pymc-labs", owner_id=uuid4())
        existing_member = FakeOrgMember(org_id=existing_org.id, user_id=user_id, role="member")

        def find_org_side(c, slug):
            if slug == "pymc-labs":
                return existing_org
            return None

        def find_member_side(c, org_id, uid):
            if org_id == existing_org.id and uid == user_id:
                return existing_member
            return None

        mock_find_org.side_effect = find_org_side
        mock_insert_org.side_effect = lambda c, slug, oid, **kwargs: FakeOrg(id=uuid4(), slug=slug, owner_id=oid)
        mock_find_member.side_effect = find_member_side
        mock_insert_member.return_value = FakeOrgMember(org_id=uuid4(), user_id=user_id, role="member")

        result = sync_user_orgs(conn, user_id, ["pymc-labs"], "testuser")

        assert "pymc-labs" in result
        # Should NOT have inserted a new member for pymc-labs
        pymc_inserts = [c for c in mock_insert_member.call_args_list if c[0][1] == existing_org.id]
        assert len(pymc_inserts) == 0

    @patch("decision_hub.infra.database.insert_org_member")
    @patch("decision_hub.infra.database.find_org_member")
    @patch("decision_hub.infra.database.insert_organization")
    @patch("decision_hub.infra.database.find_org_by_slug")
    def test_skips_invalid_slugs(self, mock_find_org, mock_insert_org, mock_find_member, mock_insert_member) -> None:
        """Should skip org names that don't match slug validation."""
        conn = MagicMock()
        user_id = uuid4()

        mock_find_org.return_value = None
        mock_insert_org.side_effect = lambda c, slug, oid, **kwargs: FakeOrg(id=uuid4(), slug=slug, owner_id=oid)
        mock_find_member.return_value = None
        mock_insert_member.return_value = FakeOrgMember(org_id=uuid4(), user_id=user_id, role="owner")

        # "Under_Score" -> "under_score" which has underscore -> invalid
        result = sync_user_orgs(conn, user_id, ["Under_Score", "ab"], "testuser")

        assert "ab" in result
        assert "under_score" not in result

    @patch("decision_hub.infra.database.insert_org_member")
    @patch("decision_hub.infra.database.find_org_member")
    @patch("decision_hub.infra.database.insert_organization")
    @patch("decision_hub.infra.database.find_org_by_slug")
    def test_returns_sorted_slugs(self, mock_find_org, mock_insert_org, mock_find_member, mock_insert_member) -> None:
        """Should return slugs sorted alphabetically."""
        conn = MagicMock()
        user_id = uuid4()

        mock_find_org.return_value = None
        mock_insert_org.side_effect = lambda c, slug, oid, **kwargs: FakeOrg(id=uuid4(), slug=slug, owner_id=oid)
        mock_find_member.return_value = None
        mock_insert_member.return_value = FakeOrgMember(org_id=uuid4(), user_id=user_id, role="owner")

        result = sync_user_orgs(conn, user_id, ["z-org", "a-org"], "m-user")

        assert result == ["a-org", "m-user", "z-org"]


# ---------------------------------------------------------------------------
# sync_org_github_metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FakeOrgFull:
    """Fake Organization with all metadata fields."""

    id: UUID
    slug: str
    owner_id: UUID
    is_personal: bool = False
    email: str | None = None
    avatar_url: str | None = None
    description: str | None = None
    blog: str | None = None
    github_synced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TestSyncOrgGithubMetadata:
    """sync_org_github_metadata should fetch and persist GitHub metadata."""

    @staticmethod
    def _make_engine():
        """Create a mock engine whose begin() returns a context manager."""
        engine = MagicMock()
        mock_conn = MagicMock()
        engine.begin.return_value.__enter__ = MagicMock(return_value=mock_conn)
        engine.begin.return_value.__exit__ = MagicMock(return_value=False)
        return engine, mock_conn

    @pytest.mark.asyncio
    @patch("decision_hub.infra.database.update_org_github_metadata")
    @patch("decision_hub.infra.github.fetch_user_metadata", new_callable=AsyncMock)
    @patch("decision_hub.infra.github.fetch_org_metadata", new_callable=AsyncMock)
    @patch("decision_hub.infra.database.find_org_by_slug")
    async def test_syncs_personal_via_fetch_user_metadata(
        self,
        mock_find_org,
        mock_fetch_org,
        mock_fetch_user,
        mock_update,
    ) -> None:
        """Personal namespace should use fetch_user_metadata."""
        engine, mock_conn = self._make_engine()
        org_id = uuid4()
        mock_find_org.return_value = FakeOrgFull(
            id=org_id,
            slug="alice",
            owner_id=uuid4(),
            is_personal=True,
        )
        mock_fetch_user.return_value = {
            "avatar_url": "https://avatar/alice",
            "email": "alice@test.com",
            "description": "I code",
            "blog": "https://alice.dev",
        }

        await sync_org_github_metadata(engine, "gh-token", ["alice"], "Alice")

        mock_fetch_user.assert_called_once_with("gh-token", "Alice")
        mock_fetch_org.assert_not_called()
        mock_update.assert_called_once_with(
            mock_conn,
            org_id,
            avatar_url="https://avatar/alice",
            email="alice@test.com",
            description="I code",
            blog="https://alice.dev",
        )

    @pytest.mark.asyncio
    @patch("decision_hub.infra.database.update_org_github_metadata")
    @patch("decision_hub.infra.github.fetch_user_metadata", new_callable=AsyncMock)
    @patch("decision_hub.infra.github.fetch_org_metadata", new_callable=AsyncMock)
    @patch("decision_hub.infra.database.find_org_by_slug")
    async def test_syncs_org_via_fetch_org_metadata(
        self,
        mock_find_org,
        mock_fetch_org,
        mock_fetch_user,
        mock_update,
    ) -> None:
        """Non-personal orgs should use fetch_org_metadata."""
        engine, _ = self._make_engine()
        org_id = uuid4()
        mock_find_org.return_value = FakeOrgFull(
            id=org_id,
            slug="pymc-labs",
            owner_id=uuid4(),
        )
        mock_fetch_org.return_value = {
            "avatar_url": "https://avatar/pymc",
            "email": "info@pymc.com",
            "description": "Bayesian",
            "blog": "https://pymc.io",
        }

        await sync_org_github_metadata(engine, "gh-token", ["pymc-labs"], "alice")

        mock_fetch_org.assert_called_once_with("gh-token", "pymc-labs")
        mock_fetch_user.assert_not_called()
        mock_update.assert_called_once()

    @pytest.mark.asyncio
    @patch("decision_hub.infra.database.update_org_github_metadata")
    @patch("decision_hub.infra.github.fetch_user_metadata", new_callable=AsyncMock)
    @patch("decision_hub.infra.github.fetch_org_metadata", new_callable=AsyncMock)
    @patch("decision_hub.infra.database.find_org_by_slug")
    async def test_skips_recently_synced_org(
        self,
        mock_find_org,
        mock_fetch_org,
        mock_fetch_user,
        mock_update,
    ) -> None:
        """Should skip orgs synced within the last 24 hours."""
        engine, _ = self._make_engine()
        recent = datetime.now(UTC) - timedelta(hours=1)
        mock_find_org.return_value = FakeOrgFull(
            id=uuid4(),
            slug="pymc-labs",
            owner_id=uuid4(),
            github_synced_at=recent,
        )

        await sync_org_github_metadata(engine, "gh-token", ["pymc-labs"], "alice")

        mock_fetch_org.assert_not_called()
        mock_fetch_user.assert_not_called()
        mock_update.assert_not_called()

    @pytest.mark.asyncio
    @patch("decision_hub.infra.database.update_org_github_metadata")
    @patch("decision_hub.infra.github.fetch_user_metadata", new_callable=AsyncMock)
    @patch("decision_hub.infra.github.fetch_org_metadata", new_callable=AsyncMock)
    @patch("decision_hub.infra.database.find_org_by_slug")
    async def test_syncs_stale_org(
        self,
        mock_find_org,
        mock_fetch_org,
        mock_fetch_user,
        mock_update,
    ) -> None:
        """Should sync orgs that were last synced more than 24 hours ago."""
        engine, _ = self._make_engine()
        stale = datetime.now(UTC) - timedelta(hours=25)
        mock_find_org.return_value = FakeOrgFull(
            id=uuid4(),
            slug="pymc-labs",
            owner_id=uuid4(),
            github_synced_at=stale,
        )
        mock_fetch_org.return_value = {
            "avatar_url": None,
            "email": None,
            "description": None,
            "blog": None,
        }

        await sync_org_github_metadata(engine, "gh-token", ["pymc-labs"], "alice")

        mock_fetch_org.assert_called_once()
        mock_update.assert_called_once()

    @pytest.mark.asyncio
    @patch("decision_hub.infra.database.update_org_github_metadata")
    @patch("decision_hub.infra.github.fetch_user_metadata", new_callable=AsyncMock)
    @patch("decision_hub.infra.github.fetch_org_metadata", new_callable=AsyncMock)
    @patch("decision_hub.infra.database.find_org_by_slug")
    async def test_continues_on_individual_org_failure(
        self,
        mock_find_org,
        mock_fetch_org,
        mock_fetch_user,
        mock_update,
    ) -> None:
        """Failure on one org should not prevent syncing others."""
        engine, _ = self._make_engine()
        org_a_id = uuid4()
        org_b_id = uuid4()

        def find_side(c, slug):
            if slug == "org-a":
                return FakeOrgFull(id=org_a_id, slug="org-a", owner_id=uuid4())
            if slug == "org-b":
                return FakeOrgFull(id=org_b_id, slug="org-b", owner_id=uuid4())
            return None

        mock_find_org.side_effect = find_side

        # org-a fetch fails, org-b succeeds
        call_count = 0

        async def fetch_side(token, slug):
            nonlocal call_count
            call_count += 1
            if slug == "org-a":
                raise RuntimeError("GitHub API down")
            return {"avatar_url": "url", "email": None, "description": None, "blog": None}

        mock_fetch_org.side_effect = fetch_side

        await sync_org_github_metadata(engine, "gh-token", ["org-a", "org-b"], "alice")

        # org-b should still be updated
        assert mock_update.call_count == 1
        assert mock_update.call_args[0][1] == org_b_id

    @pytest.mark.asyncio
    @patch("decision_hub.infra.database.update_org_github_metadata")
    @patch("decision_hub.infra.github.fetch_org_metadata", new_callable=AsyncMock)
    @patch("decision_hub.infra.database.find_org_by_slug")
    async def test_skips_unknown_org(
        self,
        mock_find_org,
        mock_fetch_org,
        mock_update,
    ) -> None:
        """Should skip orgs not found in the DB."""
        engine, _ = self._make_engine()
        mock_find_org.return_value = None

        await sync_org_github_metadata(engine, "gh-token", ["ghost-org"], "alice")

        mock_fetch_org.assert_not_called()
        mock_update.assert_not_called()
