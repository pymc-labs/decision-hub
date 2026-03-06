"""HTTP-aware wrappers around domain publish pipeline functions.

This module is the API boundary: it delegates to the pure domain layer
(``domain.publish_pipeline``) and translates domain exceptions into
``HTTPException`` responses.  Route handlers import from here so they
get HTTP-ready error handling without domain functions knowing about
FastAPI.

For domain-layer callers (tracker_service, crawler) that don't need HTTP
translation, import directly from ``domain.publish_pipeline`` instead.
"""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.engine import Connection

from decision_hub.domain.exceptions import (
    AdminRequiredError,
    EvalCaseParseError,
    EvalConfigError,
    GauntletRejectionError,
    ManifestParseError,
    NotOrgMemberError,
    OrgNotFoundError,
)
from decision_hub.domain.publish_pipeline import (  # noqa: F401 — re-exported for scripts/modal_app
    classify_skill_category,
    run_assessment_background,
    run_gauntlet_pipeline,
)
from decision_hub.domain.publish_pipeline import maybe_trigger_agent_assessment as _maybe_trigger_agent_assessment
from decision_hub.domain.publish_pipeline import parse_manifest_from_content as _parse_manifest_from_content
from decision_hub.domain.publish_pipeline import (
    quarantine_rejected_skill as _quarantine_rejected_skill,
)
from decision_hub.domain.publish_pipeline import require_org_membership as _require_org_membership
from decision_hub.models import GauntletReport, Organization
from decision_hub.settings import Settings


def require_org_membership(
    conn: Connection,
    org_slug: str,
    user_id: UUID,
    *,
    admin_only: bool = False,
) -> Organization:
    """Verify org exists and user is a member; return the Organisation.

    Raises HTTPException(404) if org not found, HTTPException(403) if not
    a member (or not admin when admin_only=True).
    """
    try:
        return _require_org_membership(conn, org_slug, user_id, admin_only=admin_only)
    except OrgNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotOrgMemberError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AdminRequiredError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def parse_manifest_from_content(
    skill_md_content: str,
    file_bytes: bytes,
) -> tuple[dict | None, object | None, tuple, str | None]:
    """Parse SKILL.md; raises HTTPException(422) on malformed manifests."""
    try:
        return _parse_manifest_from_content(skill_md_content, file_bytes)
    except ManifestParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EvalCaseParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def quarantine_rejected_skill(
    conn: Connection,
    s3_client,
    bucket: str,
    file_bytes: bytes,
    *,
    org_slug: str,
    skill_name: str,
    version: str,
    report: GauntletReport,
    check_results: list[dict],
    llm_reasoning: dict | None,
    publisher: str,
) -> None:
    """Upload rejected zip to quarantine, log the rejection, and raise 422."""
    try:
        _quarantine_rejected_skill(
            conn,
            s3_client,
            bucket,
            file_bytes,
            org_slug=org_slug,
            skill_name=skill_name,
            version=version,
            report=report,
            check_results=check_results,
            llm_reasoning=llm_reasoning,
            publisher=publisher,
        )
    except GauntletRejectionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def maybe_trigger_agent_assessment(
    eval_config,
    eval_cases: tuple,
    s3_key: str,
    s3_bucket: str,
    version_id,
    org_slug: str,
    skill_name: str,
    settings: Settings,
    user_id,
) -> tuple[str | None, str | None]:
    """Trigger eval assessment; raises HTTPException(422) if config but no cases."""
    try:
        return _maybe_trigger_agent_assessment(
            eval_config=eval_config,
            eval_cases=eval_cases,
            s3_key=s3_key,
            s3_bucket=s3_bucket,
            version_id=version_id,
            org_slug=org_slug,
            skill_name=skill_name,
            settings=settings,
            user_id=user_id,
        )
    except EvalConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
