"""MCP Python SDK v2 stdio adapter; read-only, locally configured tools.

Transport is stdio only. The owner of the MCP host chooses the startup catalog
and optional index, not individual tool callers. No model inference, network
fetching, file writes or arbitrary URL/filesystem access is exposed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from savoroute.api.contracts import (
    FilterInput,
    FusionWeightsInput,
    Identifier,
    Nonempty,
    PreferencesInput,
    QueryText,
)
from savoroute.mcp.bridge import CatalogBridge

Limit = Annotated[int, Field(strict=True, ge=1, le=100)]
Offset = Annotated[int, Field(strict=True, ge=0, le=1_000_000)]
PoolSize = Annotated[int, Field(strict=True, ge=1, le=1000)]
RrfK = Annotated[int, Field(strict=True, ge=1, le=10_000)]
PriceTier = Annotated[int, Field(strict=True, ge=1, le=4)]


def create_server(
    *,
    catalog_path: str | Path | None = None,
    index_path: str | Path | None = None,
):
    """Create an SDK v2 MCP server using the existing Savoroute HTTP contracts.

    Importing the MCP dependency is deferred until an MCP server is requested.
    """
    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError('Install the MCP extra: pip install -e ".[mcp]"') from exc

    bridge = CatalogBridge(catalog_path=catalog_path, index_path=index_path)
    server = MCPServer("savoroute")
    readonly = ToolAnnotations(read_only_hint=True, open_world_hint=False)

    @server.tool(annotations=readonly)
    async def catalog_metadata() -> dict[str, object]:
        """Describe the configured catalog, data provenance, and retrieval backend."""
        return await bridge.metadata()

    @server.tool(annotations=readonly)
    async def list_catalog_items(
        kind: Literal["restaurant", "recipe"] | None = None,
        cuisine: Nonempty | None = None,
        location: Nonempty | None = None,
        max_price_tier: PriceTier | None = None,
        dietary_tags: list[Nonempty] | None = None,
        offset: Offset = 0,
        limit: Limit = 20,
    ) -> dict[str, object]:
        """Browse catalog entries with explicit filters and bounded pagination."""
        return await bridge.items(
            kind=kind, cuisine=cuisine, location=location,
            max_price_tier=max_price_tier, dietary_tags=dietary_tags,
            offset=offset, limit=limit,
        )

    @server.tool(annotations=readonly)
    async def get_catalog_item(item_id: Identifier) -> dict[str, object]:
        """Inspect one catalog item, its recorded attributes and source attribution."""
        return await bridge.item(item_id)

    @server.tool(annotations=readonly)
    async def search_catalog(
        query: QueryText,
        filters: FilterInput | None = None,
        method: Literal["bm25", "overlap"] = "bm25",
        limit: Limit = 5,
    ) -> dict[str, object]:
        """Search the configured catalog with BM25 or weighted lexical overlap."""
        return await bridge.search({
            "query": query, "filters": (filters or FilterInput()).model_dump(),
            "method": method, "limit": limit,
        })

    @server.tool(annotations=readonly)
    async def rank_catalog(
        query: QueryText,
        filters: FilterInput | None = None,
        weights: FusionWeightsInput | None = None,
        query_vector: list[float] | None = None,
        rrf_k: RrfK = 60,
        pool_size: PoolSize = 50,
        limit: Limit = 5,
    ) -> dict[str, object]:
        """Fuse BM25/text/image rankings; vectors require an operator-configured index."""
        return await bridge.rank({
            "query": query, "filters": (filters or FilterInput()).model_dump(),
            "weights": weights.model_dump() if weights is not None else None,
            "query_vector": query_vector, "rrf_k": rrf_k,
            "pool_size": pool_size, "limit": limit,
        })

    @server.tool(annotations=readonly)
    async def recommend_catalog(
        query: QueryText,
        filters: FilterInput | None = None,
        preferences: PreferencesInput | None = None,
        weights: FusionWeightsInput | None = None,
        query_vector: list[float] | None = None,
        rrf_k: RrfK = 60,
        pool_size: PoolSize = 50,
        limit: Limit = 5,
    ) -> dict[str, object]:
        """Get evidence-grounded suggestions; hard filters and exclusions remain enforced."""
        return await bridge.recommend({
            "query": query, "filters": (filters or FilterInput()).model_dump(),
            "preferences": (preferences or PreferencesInput()).model_dump(),
            "weights": weights.model_dump() if weights is not None else None,
            "query_vector": query_vector, "rrf_k": rrf_k,
            "pool_size": pool_size, "limit": limit,
        })

    return server


def serve_stdio(*, catalog: str | Path | None = None, index: str | Path | None = None) -> None:
    """Serve MCP requests on stdin/stdout; no informational stdout output."""
    server = create_server(catalog_path=catalog, index_path=index)
    server.run(transport="stdio")
