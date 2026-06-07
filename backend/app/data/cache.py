"""Tiny in-memory TTL cache to avoid re-hitting rate-limited APIs within a run."""
from __future__ import annotations

import time
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float = 600.0):
        self._ttl = ttl_seconds
        self._store: dict[Any, tuple[float, Any]] = {}

    def get(self, key: Any) -> Any | None:
        hit = self._store.get(key)
        if hit is None:
            return None
        ts, value = hit
        if time.time() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        self._store[key] = (time.time(), value)
