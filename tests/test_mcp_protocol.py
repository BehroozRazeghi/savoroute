"""Real MCP v2 protocol smoke test (the `mcp` extra is installed in CI).

Run `pip install -e ".[mcp,api,dev]"` to execute locally.
"""

from __future__ import annotations

import asyncio

import pytest

from savoroute.mcp.server import create_server

mcp = pytest.importorskip("mcp", reason="MCP v2 optional dependency not installed")
Client = mcp.Client


def test_mcp_v2_client_lists_and_calls_all_tools():
    async def exercise():
        async with Client(create_server()) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert names == {
                "catalog_metadata", "list_catalog_items", "get_catalog_item",
                "search_catalog", "rank_catalog", "recommend_catalog",
            }
            assert all(tool.annotations is not None for tool in tools.tools)
            metadata = await client.call_tool("catalog_metadata", {})
            assert metadata.structured_content["catalog_items"] == 12
            item = await client.call_tool("get_catalog_item", {"item_id": "p001"})
            assert item.structured_content["item_id"] == "p001"
            listing = await client.call_tool("list_catalog_items", {"limit": 2})
            assert len(listing.structured_content["items"]) == 2
            query = {"query": "spicy tofu noodles", "limit": 3}
            search = await client.call_tool("search_catalog", query)
            assert search.structured_content["results"][0]["item"]["item_id"] == "p001"
            ranked = await client.call_tool("rank_catalog", query)
            assert ranked.structured_content["mode"] == "bm25_only"
            recommended = await client.call_tool("recommend_catalog", query)
            assert recommended.structured_content["catalog_synthetic"] is True

    asyncio.run(exercise())
