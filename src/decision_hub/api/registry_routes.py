"""Skill registry routes -- publish and resolve."""

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.engine import Connection

from decision_hub.api.deps import get_connection, get_current_user, get_s3_client, get_settings
from decision_hub.domain.publish import build_s3_key, validate_semver, validate_skill_name
from decision_hub.infra.database import (
    find_org_by_slug,
    find_org_member,
    find_skill,
    insert_skill,
    insert_version,
    resolve_version,
)
from decision_hub.infra.storage import compute_checksum, generate_presigned_url, upload_skill_zip
from decision_hub.models import User
from decision_hub.settings import Settings

router = APIRouter(prefix="/v1", tags=["registry"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class PublishResponse(BaseModel):
    """Confirmation of a published skill version."""
    skill_id: str
    version: str
    s3_key: str
    checksum: str


class ResolveResponse(BaseModel):
    """Resolved skill version with a pre-signed download URL."""
    version: str
    download_url: str
    checksum: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/publish", response_model=PublishResponse, status_code=201)
async def publish_skill(
    metadata: str = Form(...),
    zip_file: UploadFile = File(...),
    conn: Connection = Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> PublishResponse:
    """Publish a new skill version.

    Accepts multipart form data with a metadata JSON string and a zip file.
    Validates org membership, semver, and skill name before uploading to S3
    and recording the version in the database.
    """
    meta = json.loads(metadata)
    org_slug = meta["org_slug"]
    skill_name = meta["skill_name"]
    version = meta["version"]

    validate_skill_name(skill_name)
    validate_semver(version)

    # Verify the caller belongs to the target organisation
    org = find_org_by_slug(conn, org_slug)
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation not found")

    member = find_org_member(conn, org.id, current_user.id)
    if member is None:
        raise HTTPException(
            status_code=403,
            detail="You are not a member of this organisation",
        )

    # Read file contents and compute checksum
    file_bytes = await zip_file.read()
    checksum = compute_checksum(file_bytes)

    # Upload to S3
    s3_key = build_s3_key(org_slug, skill_name, version)
    upload_skill_zip(s3_client, settings.s3_bucket, s3_key, file_bytes)

    # Upsert skill record (find or create), then insert version
    skill = find_skill(conn, org.id, skill_name)
    if skill is None:
        skill = insert_skill(conn, org.id, skill_name)

    version_record = insert_version(
        conn,
        skill_id=skill.id,
        semver=version,
        s3_key=s3_key,
        checksum=checksum,
        runtime_config=None,
    )
    conn.commit()

    return PublishResponse(
        skill_id=str(skill.id),
        version=version_record.semver,
        s3_key=version_record.s3_key,
        checksum=version_record.checksum,
    )


@router.get("/resolve/{org_slug}/{skill_name}", response_model=ResolveResponse)
def resolve_skill(
    org_slug: str,
    skill_name: str,
    spec: str = "latest",
    conn: Connection = Depends(get_connection),
    s3_client=Depends(get_s3_client),
    settings: Settings = Depends(get_settings),
) -> ResolveResponse:
    """Resolve a skill version and return a pre-signed download URL.

    The ``spec`` query parameter can be ``latest`` or an exact semver string.
    """
    version = resolve_version(conn, org_slug, skill_name, spec)
    if version is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version '{spec}' not found for {org_slug}/{skill_name}",
        )

    download_url = generate_presigned_url(
        s3_client,
        settings.s3_bucket,
        version.s3_key,
    )

    return ResolveResponse(
        version=version.semver,
        download_url=download_url,
        checksum=version.checksum,
    )
