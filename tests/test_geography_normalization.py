"""Milestone 1: city correctness, OSM lineage, and fail-closed boundaries."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from savoroute.api.app import create_app
from savoroute.cli import main
from savoroute.data.catalog import CatalogError, catalog_to_dict, parse_catalog
from savoroute.domain.models import CatalogItem
from savoroute.geography.normalization import load_city_boundary, normalize_osm_catalog
from savoroute.ingestion.osm import import_osm_snapshot
from savoroute.ingestion.sources import IngestionError
from savoroute.retrieval.lexical import SearchFilters, filter_catalog

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data/sample/osm_overpass_fixture.json"


def fixture():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def legacy_catalog(snapshot):
    modern = import_osm_snapshot(snapshot, synthetic_fixture=True).catalog
    raw = catalog_to_dict(modern)
    for item in raw["items"]:
        for key in ("raw_address", "city", "region", "country", "city_id",
                    "latitude", "longitude", "city_source"):
            item.pop(key, None)
    return parse_catalog(raw)


def square_geojson(path, *, holes=(), geometry_type="Polygon"):
    # Synthetic fixture only; deliberately not a real municipal boundary.
    outer = [[-71.08, 42.34], [-71.05, 42.34], [-71.05, 42.36],
             [-71.08, 42.36], [-71.08, 42.34]]
    rings = [outer, *holes]
    geometry = {"type": geometry_type,
                "coordinates": [rings] if geometry_type == "MultiPolygon" else rings}
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": geometry},
    ]}), encoding="utf-8")
    return path


def boundary(path):
    return load_city_boundary(
        path, city="Exampleton", region="MA", country="US",
        city_id="us-ma-exampleton", source_url="https://example.org/verified-city-boundary",
    )


def test_osm_import_has_structured_city_address_and_geometry():
    catalog = import_osm_snapshot(fixture(), synthetic_fixture=True).catalog
    first, second, third = catalog.items
    assert first.city == "Exampleton"
    assert first.city_source == "osm:addr:city"
    assert first.raw_address == "12 Harbor Lane, Exampleton"
    assert first.location == "12 Harbor Lane, Exampleton"  # original presentation preserved
    assert (first.latitude, first.longitude) == (42.35, -71.06)
    assert first.country is None and first.city_id is None
    assert second.city == "Exampleton"
    assert third.city == "Otherburg"
    assert filter_catalog(catalog.items, SearchFilters(location=" Exampleton ")) == (first, second)
    assert filter_catalog(catalog.items, SearchFilters(city="exampleton")) == (first, second)
    assert filter_catalog(catalog.items, SearchFilters(city="Otherburg")) == (third,)
    assert filter_catalog(catalog.items, SearchFilters(city="Boston")) == ()


def test_untrusted_street_names_do_not_define_city():
    row = CatalogItem("r001", "restaurant", "Test", "Test", (), (), "test",
                      location="5 Boston Avenue, Cambridge", raw_address="5 Boston Avenue, Cambridge")
    boston = replace(row, item_id="r002", city="Boston", location="5 Main Street")
    cambridge = replace(row, item_id="r003", city="Cambridge")
    records = (row, boston, cambridge)
    assert filter_catalog(records, SearchFilters(location="Boston")) == (boston,)
    assert filter_catalog(records, SearchFilters(city="Boston")) == (boston,)
    assert filter_catalog(records, SearchFilters(location="5 Boston Avenue, Cambridge")) == (row, cambridge)
    assert filter_catalog(records, SearchFilters(city="Cambridge")) == (cambridge,)
    assert filter_catalog(records, SearchFilters(region="MA")) == ()
    assert filter_catalog(records, SearchFilters(location="bos")) == ()


def test_migration_from_legacy_catalog_preserves_ids_and_display_fields():
    snapshot = fixture()
    legacy = legacy_catalog(snapshot)
    assert all(item.city is None for item in legacy.items)
    result = normalize_osm_catalog(legacy, snapshot)
    assert [x.item_id for x in result.catalog.items] == [x.item_id for x in legacy.items]
    assert [x.location for x in result.catalog.items] == [x.location for x in legacy.items]
    assert result.report["matched_osm_items"] == 3
    assert result.report["city_from_osm_tag"] == 3
    assert result.report["city_unknown"] == 0
    assert not result.report["boundary_conflicts"]
    assert normalize_osm_catalog(result.catalog, snapshot).catalog == result.catalog


def test_missing_city_is_not_inferred_from_location_or_snapshot_bbox():
    snapshot = fixture()
    # Synthetic source without addr:city, but with address and valid geometry.
    snapshot["elements"].append({"type": "node", "id": 900000099,
        "lat": 42.348, "lon": -71.07,
        "tags": {"amenity": "restaurant", "name": "Mystery Restaurant",
                 "addr:street": "Boston Street", "addr:housenumber": "1"}})
    normalized = normalize_osm_catalog(legacy_catalog(snapshot), snapshot)
    mystery = next(x for x in normalized.catalog.items if x.title == "Mystery Restaurant")
    assert mystery.city is None and mystery.city_source is None
    assert mystery.raw_address == "1 Boston Street"
    assert mystery.latitude == 42.348
    assert mystery not in filter_catalog(normalized.catalog.items, SearchFilters(location="Boston"))
    assert normalized.report["city_unknown"] == 1


def test_operator_verified_boundary_enriches_only_city_missing_inside(tmp_path):
    snapshot = fixture()
    snapshot["elements"].append({"type": "node", "id": 900000099,
        "lat": 42.349, "lon": -71.07,
        "tags": {"amenity": "restaurant", "name": "Unlabeled Address"}})
    result = normalize_osm_catalog(legacy_catalog(snapshot), snapshot,
                                    boundary=boundary(square_geojson(tmp_path / "area.json", geometry_type="MultiPolygon")))
    unknown = next(x for x in result.catalog.items if x.title == "Unlabeled Address")
    assert unknown.city == "Exampleton"
    assert unknown.city_id == "us-ma-exampleton"
    assert unknown.country == "US" and unknown.region == "MA"
    assert unknown.city_source.startswith("boundary:")
    assert result.report["city_from_boundary"] == 1
    assert result.report["city_unknown"] == 0
    assert result.report["boundary"]["source_url"].startswith("https://")
    otherburg = next(x for x in result.catalog.items if x.city == "Otherburg")
    assert otherburg.city_id is None  # outside boundary, no assignment
    assert filter_catalog(result.catalog.items, SearchFilters(city="Exampleton", country="US"))


def test_boundary_conflict_does_not_rewrite_source_city(tmp_path):
    snapshot = fixture()
    result = normalize_osm_catalog(legacy_catalog(snapshot), snapshot,
                                    boundary=boundary(square_geojson(tmp_path / "boundary.json")))
    assert not result.report["boundary_conflicts"]
    # Enlarge the synthetic boundary to include Otherburg; keep OSM city and report disagreement.
    path = tmp_path / "all.json"
    outer = [[-71.10, 42.33], [-71.02, 42.33], [-71.02, 42.42], [-71.10, 42.42], [-71.10, 42.33]]
    path.write_text(json.dumps({"type": "Polygon", "coordinates": [outer]}))
    discrepant = normalize_osm_catalog(legacy_catalog(snapshot), snapshot, boundary=boundary(path))
    assert len(discrepant.report["boundary_conflicts"]) == 1
    assert discrepant.report["boundary_conflicts"][0]["source_city"] == "Otherburg"
    assert discrepant.catalog.items[-1].city == "Otherburg"


def test_boundary_holes_are_excluded(tmp_path):
    hole = [[-71.071, 42.348], [-71.069, 42.348], [-71.069, 42.350],
            [-71.071, 42.350], [-71.071, 42.348]]
    approved = boundary(square_geojson(tmp_path / "hole.json", holes=[hole]))
    assert approved.contains(42.35, -71.06)
    assert not approved.contains(42.349, -71.07)
    assert not approved.contains(42.4, -71.07)


@pytest.mark.parametrize("modification", [
    lambda g: g.update(crs={"type": "name", "properties": {"name": "EPSG:3857"}}),
    lambda g: g["features"].append(copy.deepcopy(g["features"][0])),
    lambda g: g["features"][0]["geometry"]["coordinates"][0][0].__setitem__(0, 200),
    lambda g: g["features"][0]["geometry"]["coordinates"][0].pop(),
])
def test_invalid_boundary_rejected(tmp_path, modification):
    path = square_geojson(tmp_path / "invalid.json")
    data = json.loads(path.read_text())
    modification(data)
    path.write_text(json.dumps(data))
    with pytest.raises(IngestionError):
        boundary(path)


@pytest.mark.parametrize("field,value", [
    ("latitude", True), ("longitude", "-71"), ("latitude", 91),
    ("latitude", float("nan")), ("city", ""), ("city_source", "osm:addr:city"),
])
def test_invalid_geography_fields_rejected(field, value):
    raw = catalog_to_dict(import_osm_snapshot(fixture(), synthetic_fixture=True).catalog)
    raw["items"][0][field] = value
    if field == "city_source":
        raw["items"][0]["city"] = None
    with pytest.raises(CatalogError):
        parse_catalog(raw)


def test_coordinates_require_pair_and_recipes_cannot_have_geometry():
    original = catalog_to_dict(import_osm_snapshot(fixture(), synthetic_fixture=True).catalog)
    original["items"][0]["longitude"] = None
    with pytest.raises(CatalogError, match="latitude and longitude"):
        parse_catalog(original)
    from savoroute.data.catalog import load_catalog
    demo = catalog_to_dict(load_catalog())
    next(item for item in demo["items"] if item["kind"] == "recipe")["city"] = "Boston"
    with pytest.raises(CatalogError, match="recipe must not"):
        parse_catalog(demo)


def test_api_list_search_rank_and_recommend_with_city(tmp_path):
    snapshot = fixture()
    catalog = normalize_osm_catalog(legacy_catalog(snapshot), snapshot).catalog
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog_to_dict(catalog)))
    with TestClient(create_app(catalog_path=path)) as client:
        # City match works with full street address; legacy location clients still work.
        by_location = client.get("/v1/items", params={"location": "exampleton"})
        by_city = client.get("/v1/items", params={"city": "Exampleton"})
        assert by_location.status_code == 200 and by_city.status_code == 200
        assert by_location.json()["total"] == by_city.json()["total"] == 2
        assert client.get("/v1/items", params={"city": "Otherburg"}).json()["total"] == 1
        assert client.get("/v1/items", params={"city": "Boston"}).json()["total"] == 0
        assert client.get("/v1/items", params={"region": "MA"}).json()["total"] == 0
        assert by_city.json()["items"][0]["city_source"] == "osm:addr:city"
        assert by_city.json()["items"][0]["latitude"] == 42.35
        filtered = {"city": " Exampleton ", "kind": "restaurant"}
        for endpoint in ("search", "rank", "recommend"):
            response = client.post(f"/v1/{endpoint}", json={
                "query": "Juniper Table", "filters": filtered,
            })
            assert response.status_code == 200, response.text
            assert response.json()["results"]
            assert all((row.get("item") or row)["city"] == "Exampleton"
                       for row in response.json()["results"])
        assert client.post("/v1/search", json={
            "query": "Juniper Table", "filters": {"city": " "},
        }).status_code == 422


def test_cli_backfill_and_no_overwrite(tmp_path, capsys):
    snapshot = fixture()
    legacy = tmp_path / "legacy.json"
    source = tmp_path / "source.json"
    output = tmp_path / "normalized.json"
    report = tmp_path / "report.json"
    legacy.write_text(json.dumps(catalog_to_dict(legacy_catalog(snapshot))))
    source.write_text(json.dumps(snapshot))
    args = ["geo", "normalize", "--catalog", str(legacy), "--osm", str(source),
            "--output", str(output), "--report", str(report)]
    assert main(args) == 0
    assert "Normalized 3 records" in capsys.readouterr().out
    assert main(args) == 2  # cannot silently overwrite
    assert json.loads(report.read_text())["city_from_osm_tag"] == 3
    assert main(["validate", "--catalog", str(output)]) == 0
    assert main(args + ["--boundary-city", "Unknown"]) == 2


def test_only_owned_matching_source_items_are_normalized():
    snapshot = fixture()
    catalog = legacy_catalog(snapshot)
    forged = replace(catalog.items[0], source="untrusted-third-party")
    altered = replace(catalog, items=(forged, *catalog.items[1:]))
    with pytest.raises(IngestionError, match="not OSM-owned"):
        normalize_osm_catalog(altered, snapshot)
    assert normalize_osm_catalog(replace(catalog, items=()), snapshot).report["matched_osm_items"] == 0


def test_legacy_binding_digest_stays_stable():
    import hashlib
    from dataclasses import asdict

    from savoroute.identity.registry import item_digest

    original = legacy_catalog(fixture()).items[0]
    payload = asdict(original)
    for name in ("raw_address", "city", "region", "country", "city_id",
                 "latitude", "longitude", "city_source"):
        payload.pop(name)
    expected = hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    assert item_digest(original) == expected
    changed = replace(original, city="Exampleton")
    assert item_digest(changed) != expected


def test_historic_study_bundle_remains_verifiable(tmp_path):
    import hashlib

    from savoroute.evaluation.annotations import (
        prepare_relevance_workbook,
        split_reviewer_sheets,
    )
    from savoroute.evaluation.study import prepare_osm_study, verify_osm_study
    from savoroute.retrieval.vector import catalog_fingerprint
    from savoroute.services.storage import json_text

    snapshot = fixture()
    source = tmp_path / "source.json"
    source.write_text(json.dumps(snapshot))
    catalog = import_osm_snapshot(snapshot, synthetic_fixture=True).catalog
    new_catalog_path = tmp_path / "catalog.json"
    new_catalog_path.write_text(json.dumps(catalog_to_dict(catalog)))
    queries = {"query_set_version": 1, "queries": [
        {"case_id": "a", "query": "Italian restaurant", "filters": {}, "split": "development"},
        {"case_id": "b", "query": "Otherburg restaurant", "filters": {}, "split": "test"},
    ]}
    query_path = tmp_path / "queries.json"
    query_path.write_text(json.dumps(queries))
    root = tmp_path / "study"
    prepare_osm_study(
        source_path=source, catalog_path=new_catalog_path,
        queries_path=query_path, output_dir=root,
        collected_at="2026-11-12T14:00:00Z", selection_protocol="fixture only",
        query_protocol="synthetic tests", allow_synthetic_fixture=True,
    )
    # Simulate historical snapshots produced by the old implementation: only
    # the additive geo fields differ from the deterministic importer today.
    legacy = legacy_catalog(snapshot)
    manifest = json.loads((root / "manifest.json").read_text())
    workbook = prepare_relevance_workbook(legacy, queries)
    a, b = split_reviewer_sheets(legacy, workbook)
    replacement = {
        "catalog.json": catalog_to_dict(legacy),
        "review_template.json": workbook,
        "reviewer_a.json": a,
        "reviewer_b.json": b,
    }
    for file, content in replacement.items():
        payload = json_text(content).encode()
        (root / file).write_bytes(payload)
        manifest["files"][file] = hashlib.sha256(payload).hexdigest()
    manifest["catalog_fingerprint"] = catalog_fingerprint(legacy)
    (root / "manifest.json").write_text(json_text(manifest))
    assert verify_osm_study(root)["items"] == 3
