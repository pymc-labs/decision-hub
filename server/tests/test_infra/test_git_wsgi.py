"""Test the git marketplace WSGI handler and cache."""

from decision_hub.infra.git_marketplace import MarketplaceCache, create_git_wsgi_app


def test_create_git_wsgi_app_returns_callable():
    """The factory should return a WSGI-compatible callable."""
    app = create_git_wsgi_app(repo_builder=lambda: None)
    assert callable(app)


def test_create_git_wsgi_app_503_when_no_repo():
    """Should return 503 when repo_builder returns None."""
    app = create_git_wsgi_app(repo_builder=lambda: None)
    status_holder = {}

    def start_response(status, headers):
        status_holder["status"] = status

    result = app({}, start_response)
    assert status_holder["status"] == "503 Service Unavailable"
    assert b"Marketplace not available" in result


def test_marketplace_cache_builds_on_first_access():
    """Cache should call build_fn on first access."""
    call_count = 0

    def build():
        nonlocal call_count
        call_count += 1
        return "fake-repo"

    cache = MarketplaceCache(
        build_fn=build,
        generation_fn=lambda: 1,
        ttl_seconds=300,
    )

    repo = cache.get_repo()
    assert repo == "fake-repo"
    assert call_count == 1

    # Second access within TTL should use cache
    repo2 = cache.get_repo()
    assert repo2 == "fake-repo"
    assert call_count == 1


def test_marketplace_cache_rebuilds_on_generation_change():
    """Cache should rebuild when generation counter changes."""
    generation = [1]
    build_count = [0]

    def build():
        build_count[0] += 1
        return f"repo-v{build_count[0]}"

    cache = MarketplaceCache(
        build_fn=build,
        generation_fn=lambda: generation[0],
        ttl_seconds=0,  # Always check generation
    )

    repo1 = cache.get_repo()
    assert repo1 == "repo-v1"

    # Same generation, should not rebuild (even with ttl=0, generation unchanged)
    repo2 = cache.get_repo()
    assert repo2 == "repo-v1"
    assert build_count[0] == 1

    # Bump generation
    generation[0] = 2
    repo3 = cache.get_repo()
    assert repo3 == "repo-v2"
    assert build_count[0] == 2
