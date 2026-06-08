"""Thin async wrapper around ``httpx.AsyncClient`` for the MLB Stats API.

The free MLB Stats API (``https://statsapi.mlb.com``) needs no API key. This
wrapper exists so the parsers in :mod:`app.data.mlb_stats` can be tested by
injecting a mocked client (e.g. via ``respx``) without touching the network.
"""

from __future__ import annotations

from typing import Any

import httpx

BASE_URL = "https://statsapi.mlb.com"
DEFAULT_TIMEOUT = 15.0


class StatsApiClient:
    """Async GET-only client against the MLB Stats API.

    Pass an existing ``httpx.AsyncClient`` to reuse a connection pool or to
    inject a mock transport in tests; otherwise one is created lazily and
    closed by :meth:`aclose` / the async-context-manager protocol.
    """

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict:
        """GET ``path`` and return the parsed JSON body, raising on HTTP errors."""
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> StatsApiClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
