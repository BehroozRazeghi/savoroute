"""Consumer discovery contracts: recorded facets and existing hard filters."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from savoroute.api.app import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_facets_are_whole_catalog_and_source_recorded():
    with TestClient(create_app()) as client:
        response = client.get("/v1/facets?kind=restaurant")
        assert response.status_code == 200
        data = response.json()
        assert data["api_version"] == "v1"
        assert data["catalog_synthetic"] is True
        assert data["total"] == 6
        assert data["cities"] == []  # 'location' is not a verified city.
        assert {row["value"] for row in data["cuisines"]} >= {"Japanese", "Italian"}
        assert data["price_tiers"] == [1, 2, 3, 4]
        recipes = client.get("/v1/facets?kind=recipe").json()
        assert recipes["total"] >= 3
        assert recipes["cities"] == []
        assert recipes["price_tiers"] == []


def test_facets_enforce_api_auth_and_validate_kind():
    with TestClient(create_app(api_key="secret-123")) as client:
        assert client.get("/v1/facets").status_code == 401
        assert client.get("/v1/facets", headers={"X-API-Key": "secret-123"}).status_code == 200
    with TestClient(create_app()) as client:
        assert client.get("/v1/facets?kind=unknown").status_code == 422


def test_recorded_cities_and_filters_no_address_guessing(tmp_path):
    source = json.loads((ROOT / "data/sample/catalog.json").read_text(encoding="utf-8"))
    # One explicitly recorded city, one address-only entry mentioning that city.
    source["items"][0]["city"] = "Boston"
    source["items"][0]["location"] = "Sample St, Boston"
    source["items"][1]["location"] = "Another St, Boston"
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with TestClient(create_app(catalog_path=path)) as client:
        facets = client.get("/v1/facets?kind=restaurant").json()
        assert facets["cities"] == [{"value": "Boston", "count": 1}]
        results = client.get("/v1/items?kind=restaurant&city=Boston").json()
        assert results["total"] == 1
        assert results["items"][0]["item_id"] == "r001"
        excluded = client.get("/v1/items?kind=restaurant&city=Cambridge").json()
        assert excluded["total"] == 0
        search = client.post("/v1/search", json={
            "query": "noodle", "limit": 100,
            "filters": {"kind": "restaurant", "city": "Boston", "cuisine": "Japanese"},
        })
        assert search.status_code == 200
        assert [row["item"]["item_id"] for row in search.json()["results"]] == ["r001"]


def test_price_filters_exclude_missing_data():
    with TestClient(create_app()) as client:
        page = client.get("/v1/items?kind=restaurant&max_price_tier=1").json()
        assert page["total"] == 1
        assert page["items"][0]["price_tier"] == 1
        assert client.get("/v1/items?kind=restaurant&max_price_tier=5").status_code == 422


def test_source_contract_uses_same_origin_and_url_navigation():
    source = (ROOT / "webapp/src/lib/api.ts").read_text(encoding="utf-8")
    state = (ROOT / "webapp/src/lib/searchState.ts").read_text(encoding="utf-8")
    assert "`/v1/facets?" in source
    assert "'/v1/search'" in source
    assert "max_price_tier" in source
    assert "credentials: 'same-origin'" in source
    assert "window.history.pushState" in state
    assert "window.history.replaceState" in state
