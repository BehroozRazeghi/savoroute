"""Local, in-process bridge to the established versioned HTTP service.

The MCP adapter does not implement search, fusion or recommendation logic.
Every call executes the same FastAPI handlers and Pydantic contracts as HTTP,
without opening a listener or making a network request.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import FastAPI

from savoroute.api.app import create_app


class ToolRequestError(ValueError):
    """The existing Savoroute HTTP contract rejected an MCP tool request."""


class CatalogBridge:
    """Fixed configuration, in-process catalog access via the HTTP adapter."""

    def __init__(
        self,
        *,
        catalog_path: str | Path | None = None,
        index_path: str | Path | None = None,
    ) -> None:
        # create_app validates the catalog and index fingerprints at startup.
        self._app: FastAPI = create_app(catalog_path=catalog_path, index_path=index_path)

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        payload: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        # ASGITransport does not use sockets, DNS or any remote service.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self._app),
            base_url="http://savoroute.internal",
            timeout=20,
            follow_redirects=False,
        ) as client:
            response = await client.request(method, path, params=params, json=payload)
        if response.status_code >= 400:
            # Never echo rejected user input or internal exception tracebacks.
            if response.status_code >= 500:
                raise RuntimeError("Savoroute internal service error")
            body = response.json()
            error = body.get("error", {})
            message = error.get("message", "Invalid Savoroute tool request")
            raise ToolRequestError(f"Savoroute {response.status_code}: {message}")
        return response.json()

    async def metadata(self) -> dict[str, object]:
        return await self._call("GET", "/v1/meta")

    async def items(
        self,
        *,
        kind: str | None = None,
        cuisine: str | None = None,
        location: str | None = None,
        max_price_tier: int | None = None,
        dietary_tags: list[str] | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, object]:
        params: dict[str, object] = {"offset": offset, "limit": limit}
        for name, value in (
            ("kind", kind), ("cuisine", cuisine), ("location", location),
            ("max_price_tier", max_price_tier), ("dietary_tags", dietary_tags),
        ):
            if value is not None:
                params[name] = value
        return await self._call("GET", "/v1/items", params=params)

    async def item(self, item_id: str) -> dict[str, object]:
        # URL-encode item IDs; they cannot change routes or request arbitrary URLs.
        if not isinstance(item_id, str) or not 1 <= len(item_id) <= 256:
            raise ToolRequestError("Invalid catalog item identifier")
        return await self._call("GET", f"/v1/items/{quote(item_id, safe='')}")

    async def search(self, payload: Mapping[str, object]) -> dict[str, object]:
        return await self._call("POST", "/v1/search", payload=payload)

    async def rank(self, payload: Mapping[str, object]) -> dict[str, object]:
        return await self._call("POST", "/v1/rank", payload=payload)

    async def recommend(self, payload: Mapping[str, object]) -> dict[str, object]:
        return await self._call("POST", "/v1/recommend", payload=payload)
