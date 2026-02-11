"""Taxonomy routes -- expose the skill category taxonomy to the frontend."""

from fastapi import APIRouter
from pydantic import BaseModel

from dhub_core.taxonomy import CATEGORY_TAXONOMY

public_router = APIRouter(prefix="/v1", tags=["taxonomy"])


class TaxonomyResponse(BaseModel):
    """Skill category taxonomy: groups mapped to their subcategories."""

    groups: dict[str, list[str]]


@public_router.get("/taxonomy", response_model=TaxonomyResponse)
def get_taxonomy() -> TaxonomyResponse:
    """Return the skill category taxonomy (groups → subcategories)."""
    return TaxonomyResponse(groups=CATEGORY_TAXONOMY)
