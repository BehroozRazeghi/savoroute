"""v0.17 geographic and approved-media contracts; no live APIs or remote images."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from savoroute.api.app import create_app
from savoroute.cli import main
from savoroute.data.catalog import catalog_to_dict, load_catalog
from savoroute.domain.models import Catalog, CatalogItem
from savoroute.evidence.review import catalog_digest, prepare_review, publish_evidence
from savoroute.geography.nearby import (
    GeographyError,
    NearbyIndex,
    distance_m,
    restaurant_positions,
    validated_coordinates,
)
from savoroute.ingestion.osm import import_osm_snapshot
from savoroute.media.reviewed import (
    ReviewedMediaError,
    load_reviewed_media,
    package_reviewed_media,
)

ROOT = Path(__file__).resolve().parents[1]
OSM = ROOT / "data/sample/osm_overpass_fixture_versioned.json"


def save(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def catalog_and_osm(tmp_path: Path):
    osm = json.loads(OSM.read_text(encoding="utf-8"))
    catalog = import_osm_snapshot(osm, synthetic_fixture=True).catalog
    cat = tmp_path / "catalog.json"
    save(cat, catalog_to_dict(catalog))
    return catalog, osm, cat


def test_geo_source_identity_and_deterministic_sort(tmp_path):
    catalog, osm, _cat = catalog_and_osm(tmp_path)
    positions = restaurant_positions(catalog, osm)
    assert len(positions) == 3
    assert all(entry["source_ref"].startswith(("node/", "way/", "relation/")) for entry in positions)
    index = NearbyIndex.from_snapshot(catalog, osm)
    found = index.search(42.35, -71.06, radius_m=20_000)
    assert found
    assert all(row["item"].kind == "restaurant" for row in found)
    assert [row["distance_m"] for row in found] == sorted(row["distance_m"] for row in found)
    assert index.search(42.35, -71.06, radius_m=100, limit=1)[0]["item"].item_id
    assert len(index.source_sha256) == 64


def test_geo_lon_wrap_and_validation():
    assert 0 < distance_m(0, 179.9999, 0, -179.9999) < 25
    assert validated_coordinates(0, 0) == (0, 0)
    for lat, lon in ((True, 0), (0, float("nan")), (91, 0), (-91, 0), (0, 181)):
        with pytest.raises(GeographyError, match="coordinate"):
            validated_coordinates(lat, lon)
    item = CatalogItem("r", "restaurant", "Dateline", "", (), (), "test")
    catalog = Catalog(1, "dateline", True, (item,))
    index = NearbyIndex(catalog, ({"item_id": "r", "latitude": 0, "longitude": 179.9999,
                                   "geometry_basis": "node", "source_ref": "node/1"},), "0" * 64)
    assert len(index.search(0, -179.9999, radius_m=25)) == 1
    for bad in (0, 20001, True, 1.2):
        with pytest.raises(GeographyError, match="radius"):
            index.search(0, 0, radius_m=bad)


def test_geo_rejects_stale_identity_and_synthetic_mix(tmp_path):
    catalog, osm, _ = catalog_and_osm(tmp_path)
    wrong = dict(osm, savoroute_fixture=False)
    with pytest.raises(GeographyError, match="fixture"):
        NearbyIndex.from_snapshot(catalog, wrong)
    modified = catalog_to_dict(catalog)
    modified["items"][0]["title"] = "Wrong name"
    from savoroute.data.catalog import parse_catalog
    with pytest.raises(GeographyError, match="identity"):
        NearbyIndex.from_snapshot(parse_catalog(modified), osm)


def test_nearby_http_boundaries_and_menu_unknown(tmp_path):
    catalog, osm, cat = catalog_and_osm(tmp_path)
    src = tmp_path / "osm.json"
    save(src, osm)
    with TestClient(create_app(catalog_path=cat, osm_path=src, api_key="local-secret")) as client:
        assert client.get("/v1/nearby", params={"latitude": 42.35, "longitude": -71.06}).status_code == 401
        headers = {"X-API-Key": "local-secret"}
        meta = client.get("/v1/meta", headers=headers).json()
        assert meta["geography_enabled"] is True
        assert meta["geography_restaurants"] == 3
        assert not meta["reviewed_media_enabled"]
        resp = client.get("/v1/nearby", params={"latitude": 42.35, "longitude": -71.06,
                                                "radius_m": 5000, "limit": 5}, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_version"] == "v1"
        assert data["source_sha256"]
        assert all(entry["item"]["item_id"] in {i.item_id for i in catalog.items}
                   for entry in data["results"])
        assert all(entry["geometry_basis"] in {"node", "bbox_center"} for entry in data["results"])
        assert "straight-line" in data["limitations"]
        assert client.get("/v1/nearby", params={"latitude": "nan", "longitude": 0}, headers=headers).status_code == 422
        assert client.get("/v1/nearby", params={"latitude": 90.1, "longitude": 0}, headers=headers).status_code == 422
        assert client.get("/v1/nearby", params={"latitude": 0, "longitude": 0, "radius_m": 20001}, headers=headers).status_code == 422
        assert client.get(f"/v1/items/{catalog.items[0].item_id}/evidence", headers=headers).json()["menu_status"] == "not_recorded"
        assert client.get("/v1/media/img_" + "a" * 24, headers=headers).status_code == 404
    with TestClient(create_app(catalog_path=cat)) as client:
        assert not client.get("/v1/meta").json()["geography_enabled"]
        assert client.get("/v1/nearby", params={"latitude": 42, "longitude": -71}).status_code == 409
        assert client.get("/v1/items").status_code == 200


def approved_media(tmp_path: Path, *, reject_image: bool = False):
    catalog = load_catalog()
    proposals = tmp_path / "proposals.json"
    review = tmp_path / "review.json"
    approved = tmp_path / "approved.json"
    source = tmp_path / "local.jpg"
    image = Image.new("RGB", (40, 30), (124, 65, 22))
    exif = Image.Exif()
    exif[0x010E] = "PRIVATE_IMAGE_DESCRIPTION"
    image.save(source, format="JPEG", exif=exif)
    save(proposals, {"schema_version": 1, "catalog_digest": catalog_digest(catalog), "claims": [
        {"claim_id": "image_one", "item_id": "r001", "kind": "image_url",
         "value": "https://commons.wikimedia.org/wiki/File:Example.jpg",
         "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
         "observed_on": "2026-11-11", "license": "CC-BY-4.0", "attribution": "Example Author"},
        {"claim_id": "menu_one", "item_id": "r001", "kind": "menu_url",
         "value": "https://example.org/menu", "source_url": "https://example.org/menu",
         "observed_on": "2026-11-11", "license": None, "attribution": None},
    ]})
    prepare_review(catalog, proposals, review)
    decisions = json.loads(review.read_text())
    for entry in decisions["decisions"]:
        entry.update({"decision": "reject" if reject_image and entry["claim_id"] == "image_one" else "approve",
                      "reviewer": "test-reviewer", "reason": "Fictional evidence test",
                      "reviewed_on": "2026-11-12"})
    save(review, decisions)
    publish_evidence(catalog, proposals, review, approved)
    manifest = tmp_path / "files.json"
    save(manifest, {"schema_version": 1, "catalog_digest": catalog_digest(catalog), "assets": [
        {"claim_id": "image_one", "path": source.name,
         "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
    ]})
    return catalog, approved, manifest


def test_reviewed_media_pipeline_http_integrity_and_private_key(tmp_path):
    catalog, approved, manifest = approved_media(tmp_path)
    destination = tmp_path / "published"
    bundle = package_reviewed_media(catalog, approved, manifest, destination)
    assert len(bundle["assets"]) == 1
    assert load_reviewed_media(destination, catalog, json.loads(approved.read_text())) == bundle
    entry = bundle["assets"][0]
    assert (destination / entry["file"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(destination / entry["file"]) as decoded:
        assert not decoded.getexif()
    assert "metadata removed" in entry["modifications"]
    with TestClient(create_app(evidence_path=approved, reviewed_media_path=destination,
                               api_key="mykey")) as client:
        assert client.get("/v1/items/r001/media").status_code == 401
        assert client.get(f"/v1/media/{entry['asset_id']}").status_code == 401
        h = {"X-API-Key": "mykey"}
        media = client.get("/v1/items/r001/media", headers=h)
        assert media.status_code == 200
        row = media.json()["images"][0]
        assert row["license"] == "CC-BY-4.0" and row["attribution"] == "Example Author"
        assert "review" not in row and "file" not in row
        assert client.get("/v1/items/r002/media", headers=h).json()["images"] == []
        assert client.get("/v1/items/no-such/media", headers=h).status_code == 404
        assert client.get("/v1/items/r001/evidence", headers=h).json()["menu_status"] == "reviewed_reference"
        image = client.get(f"/v1/media/{entry['asset_id']}", headers=h)
        assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
        assert image.headers["cache-control"] == "private, no-store"
        assert client.get("/v1/media/../bad", headers=h).status_code == 404
        (destination / entry["file"]).write_bytes(b"tampered")
        assert client.get(f"/v1/media/{entry['asset_id']}", headers=h).status_code == 409
    with pytest.raises(ReviewedMediaError, match="integrity"):
        load_reviewed_media(destination, catalog, json.loads(approved.read_text()))


def test_reviewed_media_fails_closed_before_creating_output(tmp_path):
    catalog, approved, manifest = approved_media(tmp_path)
    source = json.loads(manifest.read_text())
    source["assets"][0]["sha256"] = "0" * 64
    save(manifest, source)
    with pytest.raises(ReviewedMediaError, match="SHA256"):
        package_reviewed_media(catalog, approved, manifest, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    source["assets"][0]["sha256"] = hashlib.sha256((tmp_path / "local.jpg").read_bytes()).hexdigest()
    for relative in ("../local.jpg", "/etc/passwd", "../../secret.jpg"):
        source["assets"][0]["path"] = relative
        save(manifest, source)
        with pytest.raises(ReviewedMediaError, match="path"):
            package_reviewed_media(catalog, approved, manifest, tmp_path / "out")
        assert not (tmp_path / "out").exists()
    source["assets"][0]["path"] = "local.jpg"
    save(manifest, source)
    destination = tmp_path / "out"
    package_reviewed_media(catalog, approved, manifest, destination)
    with pytest.raises(ReviewedMediaError, match="already exists"):
        package_reviewed_media(catalog, approved, manifest, destination)
    with pytest.raises(ValueError, match="requires an approved"):
        create_app(reviewed_media_path=destination)


def test_rejected_image_reference_can_never_be_packaged(tmp_path):
    catalog, approved, manifest = approved_media(tmp_path, reject_image=True)
    with pytest.raises(ReviewedMediaError, match="approved"):
        package_reviewed_media(catalog, approved, manifest, tmp_path / "out")


def test_reviewed_media_cli_path(tmp_path):
    _catalog, approved, manifest = approved_media(tmp_path)
    assert main(["media", "package-reviewed", "--catalog", str(ROOT / "data/sample/catalog.json"),
                 "--evidence", str(approved), "--manifest", str(manifest),
                 "--output-dir", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out/manifest.json").is_file()


def test_nearby_and_media_web_shell_in_package():
    with TestClient(create_app()) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "img-src 'self' data: blob:" in page.headers["content-security-policy"]
        assert 'id="nearby-form"' in page.text
        assert 'id="nearby-results"' in page.text
        js = client.get("/assets/app.js").text
        assert "loadNearby" in js and "requestImageBlob" in js
        assert "navigator.geolocation" not in js
        assert client.get("/assets/api.mjs").status_code == 200


def test_media_bundle_rejects_approval_metadata_tampering(tmp_path):
    catalog, approved, manifest = approved_media(tmp_path)
    output = tmp_path / "published"
    package_reviewed_media(catalog, approved, manifest, output)
    bundle = json.loads((output / "manifest.json").read_text())
    bundle["assets"][0]["attribution"] = "Unauthorized replacement credit"
    save(output / "manifest.json", bundle)
    with pytest.raises(ReviewedMediaError, match="approved image claim"):
        load_reviewed_media(output, catalog, json.loads(approved.read_text()))
    with pytest.raises(ReviewedMediaError):
        create_app(evidence_path=approved, reviewed_media_path=output)
