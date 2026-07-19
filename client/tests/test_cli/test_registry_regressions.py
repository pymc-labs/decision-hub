"""Regression tests for `dhub.cli.registry` bugs surfaced in the
architecture-and-principal-engineer audit.

Each test locks in one specific bug fix. Cross-reference the accompanying
change in the same PR.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from dhub.cli.registry import (
    _MAX_SKILL_ZIP_BYTES,
    _download_capped,
    _render_skills_table,
    _try_resolve_run_id,
)


class TestRenderSkillsTableHandlesNullUpdatedAt:
    """`_render_skills_table` crashed with TypeError when the server sent
    `updated_at: null` (as opposed to omitting the key entirely). The fix
    coalesces None to "" before slicing.
    """

    def test_null_updated_at_does_not_crash(self) -> None:
        skills = [
            {
                "org_slug": "acme",
                "skill_name": "foo",
                "latest_version": "1.0.0",
                "updated_at": None,
            }
        ]
        # Previously: TypeError: 'NoneType' object is not subscriptable
        table = _render_skills_table(skills)
        assert table.row_count == 1

    def test_missing_updated_at_does_not_crash(self) -> None:
        skills = [
            {"org_slug": "acme", "skill_name": "foo", "latest_version": "1.0.0"},
        ]
        table = _render_skills_table(skills)
        assert table.row_count == 1

    def test_present_updated_at_is_truncated_to_date(self) -> None:
        skills = [
            {
                "org_slug": "acme",
                "skill_name": "foo",
                "latest_version": "1.0.0",
                "updated_at": "2026-07-01T12:34:56Z",
            }
        ]
        table = _render_skills_table(skills)
        assert table.row_count == 1


class TestDownloadCapped:
    """`_download_capped` enforces a byte cap so a runaway registry response
    cannot OOM the client.
    """

    @respx.mock
    def test_rejects_oversized_content_length_header(self) -> None:
        url = "https://example.test/big.zip"
        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                headers={"content-length": str(_MAX_SKILL_ZIP_BYTES + 1)},
                content=b"",
            )
        )
        with httpx.Client() as client, pytest.raises(ValueError, match="Response too large"):
            _download_capped(client, url, _MAX_SKILL_ZIP_BYTES)

    @respx.mock
    def test_rejects_when_stream_exceeds_cap(self) -> None:
        """When the server lies (or omits) Content-Length, the streaming
        guard must still trip. Fake a server that reports a small size
        but streams more bytes than it promised.
        """
        url = "https://example.test/lying.zip"
        big = b"x" * 20
        respx.get(url).mock(
            return_value=httpx.Response(
                200,
                headers={"content-length": "5"},  # honest header would be 20
                content=big,
            )
        )
        with httpx.Client() as client, pytest.raises(ValueError, match="exceeded 10 bytes"):
            _download_capped(client, url, 10)

    @respx.mock
    def test_accepts_response_within_cap(self) -> None:
        url = "https://example.test/small.zip"
        respx.get(url).mock(return_value=httpx.Response(200, content=b"payload"))
        with httpx.Client() as client:
            data = _download_capped(client, url, 1024)
        assert data == b"payload"


class TestResolveRunIdDoesNotLeakOtherSkills:
    """`_try_resolve_run_id` previously fell back to the user's most recent
    eval run *across all skills* when the requested skill/version had no
    eval report. `dhub logs alice/skill-a --follow` would then silently
    tail a run for `bob/skill-b`.
    """

    @respx.mock
    def test_missing_eval_report_returns_none_not_someone_elses_run(self) -> None:
        api = "http://api.test"

        # First: latest-version lookup succeeds.
        respx.get(f"{api}/v1/skills/acme/foo/latest-version").mock(
            return_value=httpx.Response(200, json={"version": "1.0.0"})
        )
        # Second: eval-report for the requested version doesn't exist — the
        # endpoint returns a literal JSON `null`.
        respx.get(f"{api}/v1/skills/acme/foo/eval-report").mock(return_value=httpx.Response(200, content=b"null"))
        # If the code fell back to the global list this route would fire and
        # return a run ID from a completely different skill. Registering it
        # asserts by *absence*: the sentinel should never be called.
        fallback = respx.get(f"{api}/v1/eval-runs").mock(
            return_value=httpx.Response(200, json=[{"id": "someone-elses-run"}])
        )

        result = _try_resolve_run_id("acme/foo", api, {})

        assert result is None
        # The unfiltered global list must not have been consulted at all.
        assert fallback.call_count == 0
