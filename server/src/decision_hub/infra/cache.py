"""In-memory TTL cache for hot read paths.

Provides a simple, thread-safe cache with time-based expiration.
Each entry expires independently after its TTL elapses. Designed for
slowly-changing data like taxonomy, org profiles, and skill listings
where a few seconds of staleness is acceptable.

Usage:
    cache = TTLCache(default_ttl=30)
    value = cache.get("my-key")
    if value is None:
        value = expensive_query()
        cache.set("my-key", value)
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _CacheEntry:
    """A single cached value with its expiration timestamp."""

    value: Any
    expires_at: float


@dataclass
class TTLCache:
    """Thread-safe in-memory cache with per-entry TTL expiration.

    Args:
        default_ttl: Default time-to-live in seconds for cached entries.
        max_size: Maximum number of entries. When exceeded, expired entries
                  are purged first; if still over limit, the oldest entry
                  is evicted.
    """

    default_ttl: float = 30.0
    max_size: int = 256
    _store: dict[str, _CacheEntry] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def get(self, key: str) -> Any | None:
        """Return the cached value if present and not expired, else None."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.monotonic() > entry.expires_at:
                del self._store[key]
                return None
            return entry.value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store a value with an optional per-entry TTL override."""
        ttl = ttl if ttl is not None else self.default_ttl
        with self._lock:
            if len(self._store) >= self.max_size and key not in self._store:
                self._evict_one()
            self._store[key] = _CacheEntry(
                value=value,
                expires_at=time.monotonic() + ttl,
            )

    def invalidate(self, key: str) -> None:
        """Remove a specific key from the cache."""
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all entries."""
        with self._lock:
            self._store.clear()

    def _evict_one(self) -> None:
        """Evict one entry: prefer expired, then oldest. Caller holds lock."""
        now = time.monotonic()
        # Try to find and remove an expired entry first
        for k, entry in self._store.items():
            if now > entry.expires_at:
                del self._store[k]
                return
        # No expired entries — evict the one expiring soonest
        if self._store:
            oldest_key = min(self._store, key=lambda k: self._store[k].expires_at)
            del self._store[oldest_key]
