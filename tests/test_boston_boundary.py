"""Offline tests for official Boston GIS identity and geometry validation."""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path

import pytest

from savoroute.geography.boston import (
    BOSTON_GIS_LAYER,
    download_official_boston_boundary,
    load_reviewed_boston_boundary,
    official_boundary_url,
    validate_boston_geojson,
)


@pytest.fixture
def official_fixture():
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {"CITY": "Boston"},
        "geometry": {"type": "Polygon", "coordinates": [[
            [-71.1, 42.3], [-71.0, 42.3], [-71.0, 42.4],
            [-71.1, 42.4], [-71.1, 42.3],
        ]]},
    }]}


def test_pinned_official_service_and_wgs84_query():
    url = official_boundary_url()
    assert url.startswith(f"{BOSTON_GIS_LAYER}/query?")
    assert "outSR=4326" in url
    assert "f=geojson" in url
    assert "outFields=CITY" in url


def test_official_boundary_is_identity_checked_and_sha_bound(tmp_path: Path, official_fixture):
    raw = json.dumps(official_fixture).encode()
    assert validate_boston_geojson(raw) == official_fixture
    path = tmp_path / "official.json"
    path.write_bytes(raw)
    b = load_reviewed_boston_boundary(path)
    assert b.city_id == "us-ma-boston"
    assert b.source_url == BOSTON_GIS_LAYER
    assert b.sha256 == hashlib.sha256(raw).hexdigest()
    assert b.contains(42.34, -71.06)
    assert not b.contains(42.34, -71.2)


def test_download_handles_response_bytes_only_with_pinned_endpoint(official_fixture):
    raw = json.dumps(official_fixture).encode()
    calls = []

    class Response(BytesIO):
        status = 200

    def opener(request, timeout):
        calls.append((request.full_url, timeout))
        return Response(raw)

    assert download_official_boston_boundary(opener=opener) == raw
    assert calls == [(official_boundary_url(), 30)]


@pytest.mark.parametrize("mutation", [
    lambda data: data["features"][0]["properties"].update(CITY="Cambridge"),
    lambda data: data["features"][0].update(properties={}),
    lambda data: data.update(features=[]),
    lambda data: data.update(crs={"type": "name", "properties": {"name": "EPSG:3857"}}),
    lambda data: data["features"][0]["geometry"].update(type="Point"),
    lambda data: data.update(type="ArcGISFeatureCollection"),
])
def test_rejects_non_boston_or_malformed_boundary(official_fixture, mutation):
    mutation(official_fixture)
    with pytest.raises(ValueError):
        validate_boston_geojson(json.dumps(official_fixture).encode())


def test_rejects_empty_or_oversized_boundary(official_fixture):
    with pytest.raises(ValueError, match="empty or larger"):
        validate_boston_geojson(b"")
    with pytest.raises(ValueError, match="empty or larger"):
        validate_boston_geojson(b"x" * (10 * 1024 * 1024 + 1))


def test_geometry_errors_are_rejected_after_identity_check(tmp_path: Path, official_fixture):
    official_fixture["features"][0]["geometry"]["coordinates"] = [[[-71.2, 42.0]]]
    path = tmp_path / "invalid.geojson"
    path.write_text(json.dumps(official_fixture))
    with pytest.raises(Exception, match="ring requires"):
        load_reviewed_boston_boundary(path)


def test_offline_end_to_end_script_uses_boundary_without_overwriting(tmp_path, official_fixture):
    """Synthetic city geometry exercises the exact CLI path; never called official."""
    from savoroute.data.catalog import catalog_to_dict
    from savoroute.ingestion.osm import import_osm_snapshot
    from scripts.resolve_boston_geography import main

    source_path = Path(__file__).resolve().parents[1] / 'data/sample/osm_overpass_fixture.json'
    snapshot = json.loads(source_path.read_text())
    snapshot['elements'].append({
        'type': 'node', 'id': 900000121, 'lat': 42.35, 'lon': -71.065,
        'tags': {'amenity': 'restaurant', 'name': 'Synthetic Unknown City'},
    })
    catalog = import_osm_snapshot(snapshot, synthetic_fixture=True).catalog
    catalog_path = tmp_path / 'catalog.json'
    original = json.dumps(catalog_to_dict(catalog))
    catalog_path.write_text(original)
    osm_path = tmp_path / 'source.json'
    osm_path.write_text(json.dumps(snapshot))
    polygon_path = tmp_path / 'boundary.geojson'
    polygon_path.write_text(json.dumps(official_fixture))
    output = tmp_path / 'new-catalog.json'
    report = tmp_path / 'audit.json'
    args = [
        '--catalog', str(catalog_path), '--osm', str(osm_path),
        '--boundary-file', str(polygon_path), '--output', str(output),
        '--report', str(report),
    ]
    assert main(args) == 0
    outcome = json.loads(report.read_text())
    assert outcome['city_from_boundary'] == 1
    assert outcome['city_unknown'] == 0
    assert outcome['boundary']['source_url'] == BOSTON_GIS_LAYER
    assert output.exists() and report.exists()
    assert catalog_path.read_text() == original
    assert any(x.get('city') == 'Boston' and x['title'] == 'Synthetic Unknown City'
               for x in json.loads(output.read_text())['items'])
    with pytest.raises(SystemExit, match='2'):
        main(args)
