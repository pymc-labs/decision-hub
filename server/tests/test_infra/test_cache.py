"""Tests for decision_hub.infra.cache -- in-memory TTL cache."""

from __future__ import annotations

import pytest

from decision_hub.infra import cache as cache_mod
from decision_hub.infra.cache import TTLCache


class _FakeClock:
    """Monotonic-clock substitute that advances only when explicitly told to.

    Cache tests used to call ``time.sleep`` to wait for expirations. That
    burned wall-clock time on every run and was prone to CI flakiness
    under load. The fake clock removes both problems while still exercising
    the same ``time.monotonic`` code path inside the cache.
    """

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    """Patch ``time.monotonic`` (used inside the cache) with a controllable clock."""
    fake = _FakeClock()
    monkeypatch.setattr(cache_mod.time, "monotonic", fake.monotonic)
    return fake


class TestTTLCacheBasics:
    """Core get/set/invalidate/clear operations."""

    def test_get_returns_none_for_missing_key(self) -> None:
        cache = TTLCache(default_ttl=10)
        assert cache.get("missing") is None

    def test_set_and_get(self) -> None:
        cache = TTLCache(default_ttl=10)
        cache.set("key", {"data": 42})
        assert cache.get("key") == {"data": 42}

    def test_invalidate_removes_key(self) -> None:
        cache = TTLCache(default_ttl=10)
        cache.set("key", "value")
        cache.invalidate("key")
        assert cache.get("key") is None

    def test_invalidate_nonexistent_key_is_noop(self) -> None:
        cache = TTLCache(default_ttl=10)
        cache.invalidate("nope")  # should not raise

    def test_clear_removes_all(self) -> None:
        cache = TTLCache(default_ttl=10)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None


class TestTTLCacheExpiration:
    """TTL-based expiration behaviour."""

    def test_expired_entry_returns_none(self, clock: _FakeClock) -> None:
        cache = TTLCache(default_ttl=10)
        cache.set("key", "value", ttl=0.01)
        clock.advance(0.02)
        assert cache.get("key") is None

    def test_per_entry_ttl_override(self, clock: _FakeClock) -> None:
        cache = TTLCache(default_ttl=0.01)
        cache.set("short", "fast", ttl=0.01)
        cache.set("long", "slow", ttl=10)
        clock.advance(0.02)
        assert cache.get("short") is None
        assert cache.get("long") == "slow"

    def test_expired_entry_is_cleaned_on_get(self, clock: _FakeClock) -> None:
        cache = TTLCache(default_ttl=0.01)
        cache.set("key", "value")
        clock.advance(0.02)
        # First get should clean up the expired entry
        assert cache.get("key") is None
        # Internal store should be empty
        assert len(cache._store) == 0


class TestTTLCacheEviction:
    """Max-size eviction behaviour."""

    def test_evicts_when_full(self) -> None:
        cache = TTLCache(default_ttl=60, max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        # One of the earlier entries should have been evicted
        assert len(cache._store) <= 2
        # The newest entry should still be present
        assert cache.get("c") == 3

    def test_prefers_evicting_expired_entries(self, clock: _FakeClock) -> None:
        cache = TTLCache(default_ttl=60, max_size=2)
        cache.set("expired", "old", ttl=0.01)
        cache.set("fresh", "new", ttl=60)
        clock.advance(0.02)
        # Adding a third entry should evict the expired one
        cache.set("newest", "latest")
        assert cache.get("fresh") == "new"
        assert cache.get("newest") == "latest"

    def test_overwrite_existing_key_does_not_evict(self) -> None:
        cache = TTLCache(default_ttl=60, max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("a", 10)  # overwrite, should not trigger eviction
        assert cache.get("a") == 10
        assert cache.get("b") == 2


class TestTTLCacheDisabledTTL:
    """Verify zero-TTL means caching is effectively disabled."""

    def test_zero_ttl_entry_expires_immediately(self, clock: _FakeClock) -> None:
        cache = TTLCache(default_ttl=60)
        cache.set("key", "value", ttl=0)
        # Entry's expires_at == set-time monotonic value. Any forward
        # movement should make it expired; advance by a tick to exercise
        # the > comparison.
        clock.advance(0.001)
        assert cache.get("key") is None


class TestTTLCacheThreadSafety:
    """Verify the cache doesn't corrupt under concurrent access."""

    def test_concurrent_set_and_get(self) -> None:
        import concurrent.futures

        cache = TTLCache(default_ttl=10, max_size=100)

        def writer(n: int) -> None:
            for i in range(50):
                cache.set(f"key-{n}-{i}", i)

        def reader(n: int) -> None:
            for i in range(50):
                cache.get(f"key-{n}-{i}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = []
            for n in range(4):
                futures.append(pool.submit(writer, n))
                futures.append(pool.submit(reader, n))
            for f in futures:
                f.result()  # should not raise
