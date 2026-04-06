"""BUILD-SPEED: In-memory PNG cache for rendered cards.

TTL defaults:
    precomputed (Edge Picks, Edge Detail): 900s (15 min)
    on-demand (My Matches):               300s (5 min)

Thread-safe: uses a threading.Lock so render_card_sync (pool thread)
and async coroutines (event loop thread) can both access safely.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

_LOCK = threading.Lock()


class CardCache:
    """LRU PNG cache with per-entry TTL and a hard entry/byte cap."""

    def __init__(self, max_entries: int = 500, default_ttl: int = 300) -> None:
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._max = max_entries
        self._default_ttl = default_ttl

    def get(self, key: str) -> bytes | None:
        with _LOCK:
            if key in self._cache:
                entry = self._cache[key]
                if time.time() < entry["expires"]:
                    self._cache.move_to_end(key)
                    return entry["data"]
                del self._cache[key]
        return None

    def put(self, key: str, data: bytes, ttl: int | None = None) -> None:
        with _LOCK:
            if key in self._cache:
                del self._cache[key]
            if len(self._cache) >= self._max:
                self._cache.popitem(last=False)  # LRU eviction
            self._cache[key] = {
                "data": data,
                "expires": time.time() + (ttl if ttl is not None else self._default_ttl),
            }

    def stats(self) -> dict:
        with _LOCK:
            total_bytes = sum(len(e["data"]) for e in self._cache.values())
            return {"entries": len(self._cache), "bytes": total_bytes}


# Singleton — imported by card_renderer and precompute job
card_cache = CardCache(max_entries=500, default_ttl=300)
