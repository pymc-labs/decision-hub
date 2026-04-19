"""User API-key management routes -- store, list, delete."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from decision_hub.api.deps import get_connection, get_current_user, get_settings
from decision_hub.api.rate_limit import rate_limit
from decision_hub.domain.crypto import encrypt_value
from decision_hub.infra.database import delete_api_key, insert_api_key, list_api_keys
from decision_hub.models import User
from decision_hub.settings import Settings

router = APIRouter(
    prefix="/v1/keys",
    tags=["keys"],
    # Even though every route below requires a JWT, per-IP rate-limiting
    # still buys us a cheap ceiling against a hijacked token or a misbehaving
    # client hammering the endpoint. Reuses the auth budget since this is the
    # same broad "credential-adjacent" traffic class.
    dependencies=[rate_limit("auth")],
)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


# Hard caps on both fields prevent a malicious or buggy client from stuffing
# the DB with multi-MB "keys" (the column is LargeBinary so there's no
# enforcement at the schema layer). 256 B covers every real provider name and
# every real API-key secret we've ever seen, with generous headroom.
_MAX_KEY_NAME_LEN = 64
_MAX_KEY_VALUE_LEN = 4096


class StoreKeyRequest(BaseModel):
    """Payload to store a new encrypted API key."""

    key_name: str = Field(min_length=1, max_length=_MAX_KEY_NAME_LEN)
    value: str = Field(min_length=1, max_length=_MAX_KEY_VALUE_LEN)


class StoreKeyResponse(BaseModel):
    """Confirmation that the key was stored."""

    key_name: str
    created_at: datetime


class KeySummary(BaseModel):
    """Public summary of a stored key (the value is never exposed)."""

    key_name: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=StoreKeyResponse, status_code=201)
def store_key(
    body: StoreKeyRequest,
    conn: Connection = Depends(get_connection),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
) -> StoreKeyResponse:
    """Encrypt and store an API key for the authenticated user.

    The plaintext value is encrypted with Fernet before being persisted;
    the raw value is never stored or returned.
    """
    encrypted = encrypt_value(body.value, settings.fernet_key)
    try:
        key_record = insert_api_key(conn, current_user.id, body.key_name, encrypted)
    except IntegrityError:
        logger.warning("Duplicate API key '{}' for user={}", body.key_name, current_user.username)
        raise HTTPException(
            status_code=409,
            detail=f"Key '{body.key_name}' already exists",
        ) from None

    return StoreKeyResponse(
        key_name=key_record.key_name,
        created_at=key_record.created_at,
    )


@router.get("", response_model=list[KeySummary])
def get_keys(
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> list[KeySummary]:
    """List all stored key names and creation dates for the authenticated user.

    Key values are never returned.
    """
    records = list_api_keys(conn, current_user.id)
    return [KeySummary(key_name=r.key_name, created_at=r.created_at) for r in records]


@router.delete("/{key_name}", status_code=204)
def remove_key(
    key_name: str,
    conn: Connection = Depends(get_connection),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a stored API key by name.

    Returns 404 if the key does not exist for the authenticated user.
    """
    deleted = delete_api_key(conn, current_user.id, key_name)
    if not deleted:
        raise HTTPException(status_code=404, detail="Key not found")
