"""Tests for decision_hub.domain.orgs -- organisation validation and sync logic."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from decision_hub.domain.orgs import sync_user_orgs, validate_org_slug, validate_role

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
