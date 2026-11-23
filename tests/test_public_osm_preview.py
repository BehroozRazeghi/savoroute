"""Real OSM-derived preview catalog: attribution, source tags and safe claims."""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from savoroute.api.app import create_app
from savoroute.data.catalog import load_catalog


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data/real/boston-osm-2026-11.json"


def test_osm_public_preview_uses_only_source_tagged_boston_records():
    catalog = load_catalog(CATALOG_PATH)
    assert catalog.synthetic is False
    assert len(catalog.items) == 123
    assert catalog.media == ()
    assert len({item.item_id for item in catalog.items}) == 123
    for item in catalog.items:
        assert item.kind == "restaurant"
        assert item.city == "Boston"
        assert item.city_source == "osm:addr:city"
        assert item.price_tier is None
        assert item.dietary_tags == ()
        assert item.source == "OpenStreetMap contributors"
        assert item.source_url is not None
        assert re.fullmatch(r"https://www\.openstreetmap\.org/(?:node|way|relation)/\d+", item.source_url)
        assert item.latitude is not None and item.longitude is not None
        assert item.description == "Restaurant entry from OpenStreetMap."
        assert item.country is None  # Never fill country if source lacks it


def test_real_preview_is_server_selected_not_client_selected():
    with TestClient(create_app(catalog_path=CATALOG_PATH)) as client:
        meta = client.get("/v1/meta")
        assert meta.status_code == 200
        assert meta.json()["catalog_synthetic"] is False
        assert meta.json()["catalog_items"] == 123
        facets = client.get("/v1/facets", params={"kind": "restaurant"})
        assert facets.status_code == 200
        assert facets.json()["cities"] == [{"value": "Boston", "count": 123}]
        results = client.get("/v1/items", params={"kind": "restaurant", "city": "Boston", "limit": 3})
        assert results.status_code == 200
        assert results.json()["total"] == 123
        assert all(row["source_url"].startswith("https://www.openstreetmap.org/") for row in results.json()["items"])
        recipes = client.get("/v1/items", params={"kind": "recipe", "limit": 3})
        assert recipes.status_code == 200
        assert recipes.json()["total"] == 0
        # Passing a path in a query cannot override the server's catalog.
        default = client.get("/v1/meta", params={"catalog_path": "data/sample/catalog.json"})
        assert default.json()["catalog_items"] == 123


def test_real_preview_license_and_readme_disclosure():
    documentation = (ROOT / "data/real/README.md").read_text(encoding="utf-8")
    public_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Open Database License" in documentation
    assert "2026-11-11" in documentation
    assert "ODbL" in public_readme
    assert "legacy-osm-desktop.png" in public_readme
    assert (ROOT / "docs/screenshots/legacy-osm-desktop.png").is_file()
    assert (ROOT / "docs/screenshots/legacy-osm-mobile.png").is_file()
