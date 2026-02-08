"""User API-key management routes -- store, list, delete."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from decision_hub.api.deps import get_connection, get_current_user, get_settings
from decision_hub.domain.crypto import encrypt_value
from decision_hub.infra.database import delete_api_key, insert_api_key, list_api_keys
from decision_hub.models import User
from decision_hub.settings import Settings

router = APIRouter(prefix="/v1/keys", tags=["keys"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class StoreKeyRequest(BaseModel):
    """Payload to store a new encrypted API key."""
    key_name: str
    value: str


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
        raise HTTPException(
            status_code=409,
            detail=f"Key '{body.key_name}' already exists",
        )

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
    return [
        KeySummary(key_name=r.key_name, created_at=r.created_at)
        for r in records
    ]


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
