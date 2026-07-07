"""Regression tests for CLI rendering paths against null-safe fields.

The registry can legitimately return ``updated_at: null`` (skills predating
timestamp columns) and ``orgs: null`` (server sent a null instead of a
missing key). The rendering / login code must not crash on either.
"""

from dhub.cli.registry import _render_skills_table


class TestRenderSkillsTableNullSafety:
    """`_render_skills_table` must survive missing / null fields on any row."""

    def test_null_updated_at_does_not_crash(self) -> None:
        skills = [
            {
                "org_slug": "acme",
                "skill_name": "widget",
                "category": "",
                "latest_version": "1.0.0",
                "updated_at": None,
                "safety_rating": "A",
                "download_count": 0,
                "author": "",
                "description": "",
            }
        ]
        # This used to raise `TypeError: 'NoneType' object is not subscriptable`
        # on `s.get("updated_at", "")[:10]`.
        table = _render_skills_table(skills)
        assert table.row_count == 1

    def test_missing_updated_at_defaults_to_empty(self) -> None:
        skills = [
            {
                "org_slug": "acme",
                "skill_name": "widget",
                "latest_version": "1.0.0",
                "safety_rating": "A",
            }
        ]
        table = _render_skills_table(skills)
        assert table.row_count == 1

    def test_mixed_rows_render(self) -> None:
        skills = [
            {
                "org_slug": "a",
                "skill_name": "s1",
                "latest_version": "1.0.0",
                "updated_at": None,
                "safety_rating": "B",
            },
            {
                "org_slug": "b",
                "skill_name": "s2",
                "latest_version": "0.9.0",
                "updated_at": "2026-06-01T00:00:00",
                "safety_rating": "A",
            },
        ]
        table = _render_skills_table(skills)
        assert table.row_count == 2
