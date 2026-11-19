"""Discover skills related to a published skill."""

import httpx
import typer

from dhub.cli.config import build_headers, exit_incompatible_registry, get_api_url, get_optional_token, raise_for_status
from dhub.cli.output import ErrorCode, exit_error, is_json, print_json
from dhub.core.validation import parse_skill_ref
from dhub_core.validation import validate_org_slug, validate_skill_name


def _read_similar_skills(response: httpx.Response) -> list[dict]:
    """Check the result shape before emitting any output or suggesting commands."""
    try:
        skills = response.json()
        if not isinstance(skills, list):
            exit_incompatible_registry(response.status_code)
        for skill in skills:
            validate_org_slug(skill["org_slug"])
            validate_skill_name(skill["skill_name"])
            if not isinstance(skill["description"], str) or not isinstance(skill["safety_rating"], str):
                exit_incompatible_registry(response.status_code)
    except (ValueError, KeyError, TypeError):
        exit_incompatible_registry(response.status_code)
    return skills


def similar_command(
    skill_ref: str = typer.Argument(metavar="ORG/SKILL", help="Published skill to find matches for."),
) -> None:
    """Find similar public skills in the registry."""
    try:
        org, name = parse_skill_ref(skill_ref)
        validate_org_slug(org)
        validate_skill_name(name)
    except ValueError:
        exit_error(ErrorCode.VALIDATION_ERROR, "Expected a skill reference in org/skill format.")

    try:
        response = httpx.get(
            f"{get_api_url()}/v1/skills/{org}/{name}/similar",
            headers=build_headers(get_optional_token()),
            timeout=60,
        )
    except httpx.RequestError:
        exit_error(ErrorCode.SERVICE_UNAVAILABLE, "Could not reach the registry. Check the API URL with 'dhub env'.")

    status = response.status_code
    if status == 404:
        exit_error(ErrorCode.NOT_FOUND, f"Skill '{skill_ref}' not found.", status=status)
    if status == 401:
        exit_error(ErrorCode.AUTH_REQUIRED, "Registry authentication failed. Run 'dhub login'.", status=status)
    if status == 403:
        exit_error(ErrorCode.PERMISSION_DENIED, f"Access denied for '{skill_ref}'.", status=status)
    if status == 429:
        exit_error(ErrorCode.SERVICE_UNAVAILABLE, "Too many registry requests. Try again later.", status=status)
    try:
        raise_for_status(response)
    except httpx.HTTPStatusError:
        if response.is_server_error:
            exit_error(
                ErrorCode.SERVICE_UNAVAILABLE, f"The registry returned HTTP {status}. Try again later.", status=status
            )
        exit_incompatible_registry(status)

    skills = _read_similar_skills(response)
    if is_json():
        print_json(skills)
    elif not skills:
        typer.echo(f"No similar skills found for {skill_ref}.")
    else:
        for skill in skills:
            typer.echo(f"dhub info {skill['org_slug']}/{skill['skill_name']}")
            typer.echo(f"  Grade {skill['safety_rating']}  {skill['description']}".rstrip())
