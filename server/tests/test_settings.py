"""Unit tests for Settings properties."""

from decision_hub.settings import Settings


class TestBlockedOrgs:
    """Verify blocked_orgs property parses the comma-separated slug list."""

    def test_empty_string(self):
        s = Settings.model_construct(blocked_org_slugs="")
        assert s.blocked_orgs == frozenset()

    def test_single_org(self):
        s = Settings.model_construct(blocked_org_slugs="badorg")
        assert s.blocked_orgs == frozenset({"badorg"})

    def test_multiple_orgs(self):
        s = Settings.model_construct(blocked_org_slugs="openclaw,steipete")
        assert s.blocked_orgs == frozenset({"openclaw", "steipete"})

    def test_whitespace_trimmed(self):
        s = Settings.model_construct(blocked_org_slugs=" openclaw , steipete ")
        assert s.blocked_orgs == frozenset({"openclaw", "steipete"})

    def test_lowercase_normalized(self):
        s = Settings.model_construct(blocked_org_slugs="OpenClaw,STEIPETE")
        assert s.blocked_orgs == frozenset({"openclaw", "steipete"})

    def test_empty_segments_ignored(self):
        s = Settings.model_construct(blocked_org_slugs="openclaw,,steipete,")
        assert s.blocked_orgs == frozenset({"openclaw", "steipete"})
