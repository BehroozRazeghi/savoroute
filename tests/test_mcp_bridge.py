"""MCP adapter regression tests: parity and no outbound network or inference."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from savoroute.api.app import create_app
from savoroute.cli import build_parser, main
from savoroute.data.catalog import catalog_to_dict, load_catalog
from savoroute.mcp.bridge import CatalogBridge, ToolRequestError


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def bridge():
    return CatalogBridge()


def test_metadata_uses_identical_http_contract(bridge):
    with TestClient(create_app()) as http:
        expected = http.get("/v1/meta").json()
    assert run(bridge.metadata()) == expected
    assert expected["package_version"] == "0.14.0"
    assert expected["catalog_synthetic"] is True
    assert expected["index_backend"] == "none"


def test_pagination_and_filters_match_http(bridge):
    with TestClient(create_app()) as http:
        expected = http.get("/v1/items", params={
            "kind": "recipe", "cuisine": "Japanese", "offset": 0, "limit": 2,
        }).json()
    assert run(bridge.items(kind="recipe", cuisine="Japanese", limit=2)) == expected
    assert len(expected["items"]) <= 2


def test_repeated_tags_and_hard_filters(bridge):
    with TestClient(create_app()) as http:
        expected = http.get("/v1/items", params={
            "kind": "recipe", "dietary_tags": ["vegan"], "limit": 50,
        }).json()
    result = run(bridge.items(kind="recipe", dietary_tags=["vegan"], limit=50))
    assert result == expected
    assert all("vegan" in item["dietary_tags"] for item in result["items"])


def test_item_source_and_nonexistent_item(bridge):
    result = run(bridge.item("p001"))
    assert result["item_id"] == "p001"
    assert result["source"] == "synthetic_demo"
    with pytest.raises(ToolRequestError, match="404"):
        run(bridge.item("not-found"))
    with pytest.raises(ToolRequestError, match="identifier"):
        run(bridge.item(""))
    with pytest.raises(ToolRequestError):
        run(bridge.item("a" * 257))


def test_path_characters_cannot_change_route(bridge):
    for candidate in ("../meta", "?kind=recipe", "foo/bar", "#fragment"):
        with pytest.raises(ToolRequestError):
            run(bridge.item(candidate))
    assert run(bridge.metadata())["catalog_items"] == 12


@pytest.mark.parametrize("payload", [
    {"query": "spicy tofu noodles", "filters": {"kind": "recipe"}, "limit": 2},
    {"query": "mushroom pasta", "method": "overlap"},
    {"query": "zzzznotarecipe"},
])
def test_search_matches_http_and_provenance(bridge, payload):
    with TestClient(create_app()) as http:
        expected = http.post("/v1/search", json=payload).json()
    assert run(bridge.search(payload)) == expected
    assert expected["catalog_synthetic"] is True


def test_rank_bm25_only_matches_http(bridge):
    payload = {"query": "spicy tofu", "filters": {"kind": "recipe"}, "limit": 3}
    with TestClient(create_app()) as http:
        expected = http.post("/v1/rank", json=payload).json()
    assert run(bridge.rank(payload)) == expected
    assert expected["mode"] == "bm25_only"
    assert expected["results"][0]["evidence"]


def test_recommendations_enforce_exclusions_and_source(bridge):
    payload = {"query": "spicy tofu", "preferences": {
        "excluded_item_ids": ["p001"], "cuisines": ["Japanese"],
    }}
    with TestClient(create_app()) as http:
        expected = http.post("/v1/recommend", json=payload).json()
    actual = run(bridge.recommend(payload))
    assert actual == expected
    assert "p001" not in {item["item_id"] for item in actual["results"]}
    assert all(item["retrieval_evidence"] for item in actual["results"])


@pytest.mark.parametrize(("method", "payload"), [
    ("search", {"query": ""}),
    ("search", {"query": "pasta", "limit": 0}),
    ("search", {"query": "secret-private-data", "unknown": "secret-private-data"}),
    ("rank", {"query": "pasta", "query_vector": [0.1, 0.2]}),
    ("rank", {"query": "pasta", "weights": {"bm25": 1, "text": 1, "image": 0}}),
    ("recommend", {"query": "noodles", "preferences": {
        "excluded_item_ids": ["unrecognized-item"],
    }}),
])
def test_invalid_calls_fail_closed_without_raw_payload(bridge, method, payload):
    with pytest.raises(ToolRequestError) as error:
        run(getattr(bridge, method)(payload))
    assert "secret-private-data" not in str(error.value)


@pytest.mark.parametrize("limit", [0, 101, -1, 5000])
def test_items_are_bounded(bridge, limit):
    with pytest.raises(ToolRequestError):
        run(bridge.items(limit=limit))


def test_catalog_selected_once_at_startup(tmp_path: Path):
    catalog = load_catalog()
    catalog_file = tmp_path / "catalog.json"
    catalog_file.write_text(json.dumps(catalog_to_dict(catalog)), encoding="utf-8")
    bridge = CatalogBridge(catalog_path=catalog_file)
    assert run(bridge.metadata())["catalog_items"] == 12
    # File modifications after construction do not silently replace in-memory catalog.
    catalog_file.write_text("corrupt", encoding="utf-8")
    assert run(bridge.metadata())["catalog_items"] == 12
    with pytest.raises(ValueError, match="catalog_path"):
        CatalogBridge(index_path=tmp_path / "index.json")


def test_cli_parser_and_stdio_invocation(monkeypatch, capsys):
    args = build_parser().parse_args(["mcp", "serve", "--catalog", "data/sample/catalog.json"])
    assert args.mcp_command == "serve"
    assert args.catalog == "data/sample/catalog.json"

    calls = []
    monkeypatch.setattr("savoroute.mcp.server.serve_stdio", lambda **kw: calls.append(kw))
    assert main(["mcp", "serve", "--catalog", "data/sample/catalog.json"]) == 0
    assert calls == [{"catalog": "data/sample/catalog.json", "index": None}]
    assert capsys.readouterr().out == ""


def test_stdio_server_declares_only_stdio_transport(monkeypatch):
    from savoroute.mcp import server as module

    class Stub:
        def run(self, *, transport):
            assert transport == "stdio"

    monkeypatch.setattr(module, "create_server", lambda **kw: Stub())
    module.serve_stdio()
