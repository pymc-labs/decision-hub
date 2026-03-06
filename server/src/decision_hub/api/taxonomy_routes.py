"""Taxonomy routes -- expose the skill category taxonomy to the frontend."""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from decision_hub.api.deps import get_settings
from decision_hub.settings import Settings
from dhub_core.taxonomy import CATEGORY_TAXONOMY

public_router = APIRouter(prefix="/v1", tags=["taxonomy"])


class TaxonomyResponse(BaseModel):
    """Skill category taxonomy: groups mapped to their subcategories."""

    groups: dict[str, list[str]]


@public_router.get("/taxonomy", response_model=TaxonomyResponse)
def get_taxonomy(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> TaxonomyResponse:
    """Return the skill category taxonomy (groups → subcategories)."""
    ttl = settings.cache_ttl_taxonomy
    if ttl:
        response.headers["Cache-Control"] = f"public, max-age={ttl}"
    return TaxonomyResponse(groups=CATEGORY_TAXONOMY)
