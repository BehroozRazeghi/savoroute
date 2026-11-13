"""Milestone 3: recorded evidence coverage is not verification or inference."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from savoroute.api.app import create_app
from savoroute.cli import main
from savoroute.data.catalog import load_catalog
from savoroute.ingestion.osm import import_osm_snapshot
from savoroute.quality.audit import audit_catalog, informative_description
from savoroute.quality.osm_facts import (
    SourceFactsError,
    build_osm_source_facts,
    load_source_facts,
    read_osm_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "data/generated/real-pilot"


@pytest.fixture(scope="module")
def pilot():
    """Real Boston integration data is optional and deliberately not tracked by Git."""
    path = PILOT / "catalog.json"
    if not path.is_file():
        pytest.skip("optional, Git-ignored normalized Boston pilot is not present")
    catalog = load_catalog(path)
    if sum(item.city == "Boston" for item in catalog.items) != 124:
        pytest.skip("optional Boston pilot has not been normalized to the current snapshot")
    return catalog


@pytest.fixture(scope="module")
def snapshot(pilot):
    path = PILOT / "frozen/source.json"
    if not path.is_file():
        pytest.skip("optional, Git-ignored Boston OSM snapshot is not present")
    return read_osm_snapshot(path)


@pytest.fixture(scope="module")
def facts(pilot, snapshot):
    return build_osm_source_facts(pilot, snapshot)


def test_boston_data_quality_coverage_is_exact_not_inferred(pilot, facts):
    report = audit_catalog(pilot, source_facts=facts, queue_limit=10)
    fields = report["by_kind"]["restaurant"]["fields"]
    assert report["total_records"] == 165
    assert report["by_kind"]["recipe"]["total"] == 0
    assert [fields[k]["recorded"] for k in ("city", "coordinates", "cuisines",
            "description", "price", "dietary_tags", "media_refs")] == [124, 165, 111, 0, 0, 0, 0]
    assert report["source_observations"]["by_field"]["website"] == 124
    assert report["source_observations"]["by_field"]["opening_hours"] == 62
    assert report["source_observations"]["by_field"]["cuisine_tag"] == 111
    assert report["source_observations"]["by_field"]["city_tag"] == 124
    assert report["source_observations"]["records_with_source_observations"] == 156
    assert report["review_queue_total"] == 165
    assert len(report["review_queue"]) == 10
    assert all(r["priority"] >= 0 for r in report["review_queue"])
    assert fields["price"]["missing"] == 165
    assert fields["description"]["recorded_pct"] == 0.0


def test_audit_rejects_negative_queue_and_stale_sidecar(pilot, facts):
    with pytest.raises(ValueError, match="queue_limit"):
        audit_catalog(pilot, queue_limit=-1)
    with pytest.raises(ValueError, match="different catalog"):
        audit_catalog(load_catalog(), source_facts=facts)
    demo = audit_catalog(load_catalog())
    assert demo["synthetic"] is True
    assert demo["by_kind"]["recipe"]["total"] > 0


def test_osm_snapshot_provenance_and_no_dietary_inference(facts, pilot):
    assert facts["schema_version"] == 1
    assert facts["observed_at"] == "2026-11-11T21:22:47Z"
    assert facts["license"] == "ODbL-1.0"
    assert len(facts["records"]) == 165
    assert {entry["item_id"] for entry in facts["records"]} == {x.item_id for x in pilot.items}
    assert all(entry["source_url"].startswith("https://www.openstreetmap.org/")
               for entry in facts["records"])
    assert all(item.dietary_tags == () and item.price_tier is None for item in pilot.items)
    assert any(fact["field"] == "diet_vegan" for row in facts["records"] for fact in row["facts"])
    assert all(not informative_description(item) for item in pilot.items)


def test_reject_source_catalog_identity_mismatch(pilot, snapshot):
    other = copy.deepcopy(snapshot)
    other["elements"][0]["tags"]["name"] = "not its actual name"
    with pytest.raises(SourceFactsError, match="name differs"):
        build_osm_source_facts(pilot, other)
    other = copy.deepcopy(snapshot)
    other["elements"].pop()
    with pytest.raises(SourceFactsError, match="missing records"):
        build_osm_source_facts(pilot, other)
    other = copy.deepcopy(snapshot)
    other["osm3s"]["timestamp_osm_base"] = "2026-11-11"  # timezone required
    with pytest.raises(SourceFactsError, match="timezone"):
        build_osm_source_facts(pilot, other)
    with pytest.raises(SourceFactsError, match="synthetic"):
        build_osm_source_facts(load_catalog(), snapshot)


def test_invalid_urls_and_bad_tag_values_are_discarded_not_executed(pilot, snapshot):
    altered = copy.deepcopy(snapshot)
    tags = altered["elements"][0]["tags"]
    tags["website"] = "javascript:alert(1)"
    tags["website:menu"] = "https://127.0.0.1/private"
    tags["opening_hours"] = "bad\x00data"
    tags["diet:gluten_free"] = "definitely safe for severe allergy"  # unsupported enum
    product = build_osm_source_facts(pilot, altered)
    row = next(r for r in product["records"] if r["osm_ref"] == f"{altered['elements'][0]['type']}/{altered['elements'][0]['id']}")
    assert not any(f["field"] in {"website", "menu_url", "opening_hours", "diet_gluten_free"}
                   for f in row["facts"])


def test_file_validation_tamper_and_stale_catalog(pilot, facts, tmp_path):
    path = tmp_path / "facts.json"
    path.write_text(json.dumps(facts), encoding="utf-8")
    assert len(load_source_facts(path, pilot)["records"]) == 165
    with pytest.raises(SourceFactsError, match="catalog or provenance mismatch"):
        load_source_facts(path, load_catalog())
    bad = copy.deepcopy(facts)
    bad["records"][0]["facts"].append({"field": "verified_allergen_safe", "value": "yes", "osm_tag": "diet:vegan"})
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(SourceFactsError, match="unsupported or duplicate"):
        load_source_facts(path, pilot)
    bad = copy.deepcopy(facts)
    bad["records"][0]["osm_ref"] = "node/999"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(SourceFactsError, match="identity"):
        load_source_facts(path, pilot)
    bad = copy.deepcopy(facts)
    bad["records"][0]["source_url"] = "https://example.com"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(SourceFactsError, match="catalog identity"):
        load_source_facts(path, pilot)


def test_quality_cli_exclusive_outputs_and_no_mutation(pilot, tmp_path):
    report, facts_path = tmp_path / "report.json", tmp_path / "source-facts.json"
    catalog_path, osm_path = PILOT / "catalog.json", PILOT / "frozen/source.json"
    before = (catalog_path.read_bytes(), osm_path.read_bytes())
    argv = ["quality", "audit", "--catalog", str(catalog_path), "--osm", str(osm_path),
            "--report", str(report), "--source-facts-out", str(facts_path)]
    assert main(argv) == 0
    assert json.loads(report.read_text())["by_kind"]["restaurant"]["total"] == 165
    assert len(load_source_facts(facts_path, pilot)["records"]) == 165
    assert main(argv) == 2  # never overwrite output
    assert main(["quality", "audit", "--catalog", str(catalog_path),
                 "--report", str(osm_path)]) == 2  # never overwrite input
    assert main(["quality", "audit", "--catalog", str(catalog_path),
                 "--report", str(tmp_path / "x.json"), "--osm", str(osm_path)]) == 2
    assert before == (catalog_path.read_bytes(), osm_path.read_bytes())


def test_api_source_facts_optional_and_authenticated(pilot, facts, tmp_path):
    sidecar = tmp_path / "source-facts.json"
    sidecar.write_text(json.dumps(facts), encoding="utf-8")
    item_id = next(row["item_id"] for row in facts["records"] if row["facts"])
    with TestClient(create_app(catalog_path=PILOT / "catalog.json", source_facts_path=sidecar,
                               api_key="topsecret")) as client:
        assert client.get("/v1/items/" + item_id + "/source-facts").status_code == 401
        headers = {"X-API-Key": "topsecret"}
        meta = client.get("/v1/meta", headers=headers).json()
        assert meta["source_facts_enabled"] is True and meta["source_facts_records"] == 165
        response = client.get("/v1/items/" + item_id + "/source-facts", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        assert payload["verification_status"] == "unverified_osm_tags"
        assert payload["facts"]
        assert "live" in payload["limitations"] or "stale" in payload["limitations"]
        assert client.get("/v1/items/not-real/source-facts", headers=headers).status_code == 404
        # Source facts do not change the default search/filter/recommendations.
        assert client.get("/v1/items", params={"city": "Boston"}, headers=headers).json()["total"] == 124
    with TestClient(create_app()) as client:
        assert client.get("/v1/meta").json()["source_facts_enabled"] is False
        id_demo = load_catalog().items[0].item_id
        assert client.get("/v1/items/" + id_demo + "/source-facts").json() == {
            "api_version": "v1", "item_id": id_demo, "observed_at": None,
            "source_url": None, "source_timestamp": None, "attribution": None, "license": None,
            "verification_status": "not_configured", "facts": [],
            "limitations": "Source-supplied OSM observations are not independently verified; "
                           "opening hours, dietary claims, accessibility, reservation, "
                           "service and website availability may be stale or incorrect. "
                           "Do not treat dietary tags as allergen safety evidence.",
        }


def test_no_real_recipe_data_and_demo_is_fictional(pilot):
    assert not any(item.kind == "recipe" for item in pilot.items)
    demo = load_catalog()
    assert demo.synthetic is True
    assert any(item.kind == "recipe" for item in demo.items)
    assert audit_catalog(pilot)["by_kind"]["recipe"]["fields"]["ingredients"]["recorded_pct"] is None


def test_api_rejects_a_mismatched_live_geometry_snapshot(facts, tmp_path):
    sidecar = tmp_path / "facts.json"
    sidecar.write_text(json.dumps(facts), encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot differs from source-facts"):
        create_app(catalog_path=PILOT / "catalog.json", source_facts_path=sidecar,
                   osm_path=ROOT / "data/sample/osm_overpass_fixture.json")
    # The exact previously saved source is accepted when spatial discovery is enabled.
    with TestClient(create_app(catalog_path=PILOT / "catalog.json", source_facts_path=sidecar,
                               osm_path=PILOT / "frozen/source.json")) as client:
        assert client.get("/v1/meta").json()["geography_enabled"] is True
        assert client.get("/v1/meta").json()["source_facts_records"] == 165


def test_source_observations_against_committed_fictional_osm_fixture(tmp_path):
    """Always-run source-facts/API test, independent of ignored Boston pilot files.

    This OSM-shaped fixture is fictional; importing without the fixture marker
    only exercises the non-synthetic code path. It is not real venue evidence.
    """
    sample = ROOT / "data/sample/osm_overpass_fixture.json"
    snapshot = json.loads(sample.read_text(encoding="utf-8"))
    snapshot.pop("savoroute_fixture")
    snapshot["osm3s"] = {"timestamp_osm_base": "2026-11-11T21:22:47Z"}
    snapshot["elements"][0]["tags"]["website"] = "https://example.org/restaurant"
    source = import_osm_snapshot(snapshot).catalog
    facts = build_osm_source_facts(source, snapshot)
    assert len(facts["records"]) == len(source.items) == 3
    assert facts["verification_status"] == "unverified_osm_tags"
    report = audit_catalog(source, source_facts=facts)
    assert report["by_kind"]["restaurant"]["total"] == 3
    assert report["source_observations"]["by_field"]["website"] == 1
    from savoroute.data.catalog import catalog_to_dict
    catalog_file = tmp_path / "catalog.json"
    facts_file = tmp_path / "facts.json"
    catalog_file.write_text(json.dumps(catalog_to_dict(source)), encoding="utf-8")
    facts_file.write_text(json.dumps(facts), encoding="utf-8")
    with TestClient(create_app(catalog_path=catalog_file, source_facts_path=facts_file,
                               api_key="test-only-key")) as client:
        assert client.get("/v1/meta").status_code == 401
        headers = {"X-API-Key": "test-only-key"}
        assert client.get("/v1/meta", headers=headers).json()["source_facts_records"] == 3
        response = client.get("/v1/items/" + source.items[0].item_id + "/source-facts",
                              headers=headers)
        assert response.status_code == 200
        assert response.json()["verification_status"] == "unverified_osm_tags"
