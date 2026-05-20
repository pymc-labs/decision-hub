"""Contract test: every endpoint on a public router must be rate-limited.

Per ``CLAUDE.md``, all public endpoints have to declare a sliding-window
rate-limit dependency. This test enforces the rule mechanically so that
adding a new unauthenticated endpoint without a rate limit fails CI rather
than slipping through review.

It also includes a static assertion that the five specific endpoints fixed
in this PR are protected, so a future refactor cannot silently drop them.
"""

from collections.abc import Iterable

import pytest
from fastapi.routing import APIRoute

from decision_hub.api.org_routes import org_public_router
from decision_hub.api.rate_limit import RateLimiter, enforce_public_reads_rate_limit
from decision_hub.api.registry_routes import (
    _enforce_audit_log_rate_limit,
    _enforce_download_rate_limit,
    _enforce_list_skills_rate_limit,
    _enforce_resolve_rate_limit,
    _enforce_scan_report_rate_limit,
    _enforce_similar_skills_rate_limit,
)
from decision_hub.api.registry_routes import public_router as registry_public_router
from decision_hub.api.search_routes import _enforce_search_rate_limit
from decision_hub.api.search_routes import router as search_router
from decision_hub.api.taxonomy_routes import public_router as taxonomy_public_router

# Functions that count as a rate-limit dependency. Adding a new one here
# is intentional friction — if you introduce a new RateLimiter-backed
# dependency, register it explicitly.
_RATE_LIMIT_DEPS = {
    enforce_public_reads_rate_limit,
    _enforce_audit_log_rate_limit,
    _enforce_download_rate_limit,
    _enforce_list_skills_rate_limit,
    _enforce_resolve_rate_limit,
    _enforce_scan_report_rate_limit,
    _enforce_similar_skills_rate_limit,
    _enforce_search_rate_limit,
}


def _route_dependencies(route: APIRoute) -> Iterable:
    """Yield the ``dependant`` callables transitively attached to a route."""
    deps = list(getattr(route.dependant, "dependencies", []))
    while deps:
        dep = deps.pop()
        if dep.call is not None:
            yield dep.call
        deps.extend(dep.dependencies)


def _has_rate_limit(route: APIRoute) -> bool:
    """True when the route declares a known rate-limit dependency."""
    for call in _route_dependencies(route):
        if call in _RATE_LIMIT_DEPS:
            return True
        # Defensive: if a future dependency wraps a RateLimiter instance
        # directly (e.g. ``Depends(some_limiter_instance)``), accept it.
        if isinstance(call, RateLimiter):
            return True
    return False


# Routers whose every endpoint must be rate-limited because they are
# mounted with no authentication dependency in ``api/app.py``. We exclude
# ``search_router`` from the "every route" sweep because POST/GET ``/ask``
# already declares ``_enforce_search_rate_limit`` — but we still assert
# below that the search router is fully covered.
_PUBLIC_ROUTERS = [
    ("registry_public_router", registry_public_router),
    ("org_public_router", org_public_router),
    ("taxonomy_public_router", taxonomy_public_router),
    ("search_router", search_router),
]


def _flatten_routes() -> list[tuple[str, APIRoute]]:
    out: list[tuple[str, APIRoute]] = []
    for name, router in _PUBLIC_ROUTERS:
        for route in router.routes:
            if isinstance(route, APIRoute):
                out.append((name, route))
    return out


@pytest.mark.parametrize(
    "router_name,route",
    _flatten_routes(),
    ids=lambda v: v.path if isinstance(v, APIRoute) else v,
)
def test_every_public_route_has_a_rate_limit(router_name: str, route: APIRoute) -> None:
    """A failing case means a new public endpoint was added without a limiter.

    Either decorate the endpoint with
    ``dependencies=[Depends(enforce_public_reads_rate_limit)]`` (or another
    appropriate per-purpose limiter), or — if the endpoint really should be
    unrated — register the new dependency in ``_RATE_LIMIT_DEPS`` above with
    a justification.
    """
    assert _has_rate_limit(route), (
        f"Public route {route.methods} {route.path} on {router_name} has no rate-limit "
        "dependency. Add one (see CLAUDE.md 'Rate Limiting & DOS Protection')."
    )


@pytest.mark.parametrize(
    "path",
    [
        "/v1/stats",
        "/v1/skills/{org_slug}/{skill_name}/summary",
        "/v1/orgs/stats",
        "/v1/orgs/profiles",
        "/v1/orgs/{slug}/profile",
    ],
)
def test_specific_endpoints_use_public_reads_limiter(path: str) -> None:
    """Pin the specific endpoints this PR brought under the public-reads budget.

    A future refactor that silently swaps the dependency for something else
    or drops it entirely will be caught here, even if the broader contract
    test above is satisfied by a different limiter.
    """
    matching = []
    for _, route in _flatten_routes():
        if route.path == path:
            matching.append(route)
    assert matching, f"No public route registered at {path}"
    for route in matching:
        deps = list(_route_dependencies(route))
        assert enforce_public_reads_rate_limit in deps, (
            f"{path} must depend on enforce_public_reads_rate_limit; got {deps}"
        )
