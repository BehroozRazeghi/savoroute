"""Identity and snapshot update invariants (offline, fictional fixtures)."""

import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from savoroute.cli import main
from savoroute.data.catalog import catalog_to_dict, load_catalog
from savoroute.domain.models import Catalog, MediaAsset
from savoroute.identity.registry import (
    EntityRegistry,
    SourceBinding,
    bootstrap_osm_registry,
    link_source,
    load_registry,
    parse_registry,
)
from savoroute.ingestion.osm import import_osm_snapshot
from savoroute.ingestion.sources import IngestionError
from savoroute.services.osm_sync import sync_osm_snapshot, write_osm_sync

FIXTURE = Path("data/sample/osm_overpass_fixture.json")
UPDATE = Path("data/sample/osm_overpass_update_fixture.json")


@pytest.fixture
def previous():
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = import_osm_snapshot(original, synthetic_fixture=True)
    registry = bootstrap_osm_registry(result.catalog, result.report())
    return result.catalog, registry


def test_bootstrap_binds_only_admitted_records(previous):
    catalog, registry = previous
    assert len(registry.bindings) == 3
    assert registry.lookup("osm", "way/900000002") is None  # review, not admitted
    for binding in registry.bindings:
        assert catalog.get(binding.item_id) is not None
    assert parse_registry(registry.as_dict(), catalog) == registry


def test_bootstrap_rejects_mismatched_catalog(previous):
    catalog, _ = previous
    report = import_osm_snapshot(json.loads(FIXTURE.read_text()), synthetic_fixture=True).report()
    mutated = Catalog(1, "wrong-dataset", True, catalog.items, catalog.media)
    with pytest.raises(IngestionError, match="digest"):
        bootstrap_osm_registry(mutated, report)
    report["admitted_sources"][0]["item_id"] = "missing_id"
    with pytest.raises(IngestionError, match="disagree"):
        bootstrap_osm_registry(catalog, report)


def test_sync_updates_without_changing_ids_or_media(previous):
    catalog, registry = previous
    first = catalog.items[0]
    image = MediaAsset("m_sample", first.item_id, "image", "fixture://demo", "test")
    with_media = Catalog(1, catalog.dataset_name, True, catalog.items, (image,))
    before_ids = {item.item_id for item in catalog.items}
    update = json.loads(UPDATE.read_text(encoding="utf-8"))
    result = sync_osm_snapshot(update, base_catalog=with_media,
                               registry=registry, synthetic_fixture=True)
    statuses = [row.status for row in result.decisions]
    assert statuses == ["updated", "review", "admitted"]
    assert len(result.catalog.items) == 4
    assert before_ids.issubset({row.item_id for row in result.catalog.items})
    assert result.catalog.media == (image,)
    assert result.catalog.get(first.item_id).cuisines == ("italian", "pizza", "mediterranean")
    assert result.registry.lookup("osm", "node/900000001").item_id == first.item_id
    assert result.registry.lookup("osm", "node/900000007") is not None
    assert result.registry.lookup("osm", "way/900000002") is None


def test_repeated_sync_is_idempotent(previous):
    catalog, registry = previous
    payload = json.loads(UPDATE.read_text())
    first = sync_osm_snapshot(payload, base_catalog=catalog, registry=registry, synthetic_fixture=True)
    second = sync_osm_snapshot(payload, base_catalog=first.catalog,
                               registry=first.registry, synthetic_fixture=True)
    assert [entry.status for entry in second.decisions] == ["unchanged", "review", "unchanged"]
    assert second.catalog == first.catalog
    assert second.registry == first.registry


def test_absence_in_new_snapshot_never_deletes_existing(previous):
    catalog, registry = previous
    payload = {"savoroute_fixture": True, "elements": []}
    result = sync_osm_snapshot(payload, base_catalog=catalog,
                               registry=registry, synthetic_fixture=True)
    assert result.catalog == catalog
    assert result.registry == registry
    assert result.decisions == ()


def test_invalid_known_source_requires_review(previous):
    catalog, registry = previous
    payload = json.loads(UPDATE.read_text())
    payload["elements"] = [payload["elements"][0]]
    del payload["elements"][0]["tags"]["name"]
    result = sync_osm_snapshot(payload, base_catalog=catalog,
                               registry=registry, synthetic_fixture=True)
    assert result.decisions[0].status == "review"
    assert result.catalog == catalog


def test_changed_source_name_colliding_with_other_item_requires_review(previous):
    catalog, registry = previous
    payload = json.loads(UPDATE.read_text())
    candidate = payload["elements"][0]
    candidate["tags"]["name"] = catalog.items[1].title
    candidate["tags"]["addr:full"] = catalog.items[1].location
    payload["elements"] = [candidate]
    result = sync_osm_snapshot(payload, base_catalog=catalog,
                               registry=registry, synthetic_fixture=True)
    assert result.decisions[0].status == "review"
    assert result.catalog == catalog


def test_manual_link_does_not_modify_catalog(previous):
    catalog, registry = previous
    linked = link_source(registry, catalog, provider="guide", source_ref="record-44",
                         item_id=catalog.items[0].item_id)
    assert linked.lookup("guide", "record-44").item_id == catalog.items[0].item_id
    assert registry.lookup("guide", "record-44") is None
    with pytest.raises(IngestionError, match="already exists"):
        link_source(linked, catalog, provider="guide", source_ref="record-44",
                    item_id=catalog.items[1].item_id)
    with pytest.raises(IngestionError, match="missing item"):
        link_source(registry, catalog, provider="guide", source_ref="record-5",
                    item_id="i_missing")


@pytest.mark.parametrize("bad", [
    {"provider": "OSM", "source_ref": "node/1", "item_id": "sample"},
    {"provider": "osm", "source_ref": "node/not-id", "item_id": "sample"},
    {"provider": "foodguide", "source_ref": "bad\nref", "item_id": "sample"},
    {"provider": "osm", "source_ref": "node/1", "item_id": "sample",
     "latitude": 999., "longitude": 1.},
    {"provider": "osm", "source_ref": "node/1", "item_id": "sample",
     "source_sha256": "abc"},
])
def test_reject_invalid_bindings(bad):
    with pytest.raises(IngestionError):
        SourceBinding(**bad)


def test_registry_rejects_duplicates_and_dangling_refs(previous):
    catalog, registry = previous
    raw = registry.as_dict()
    raw["bindings"].append(copy.deepcopy(raw["bindings"][0]))
    with pytest.raises(IngestionError, match="duplicate"):
        parse_registry(raw, catalog)
    raw["bindings"][-1]["source_ref"] = "node/991000"
    raw["bindings"][-1]["item_id"] = "missing"
    with pytest.raises(IngestionError, match="missing"):
        parse_registry(raw, catalog)


def test_conflict_on_duplicate_snapshot_source(previous):
    catalog, registry = previous
    payload = json.loads(FIXTURE.read_text())
    payload["elements"] = [payload["elements"][0]] * 2
    with pytest.raises(IngestionError, match="duplicate"):
        sync_osm_snapshot(payload, base_catalog=catalog,
                          registry=registry, synthetic_fixture=True)


def test_manual_multiple_osm_links_disable_automatic_source_updates(previous):
    catalog, registry = previous
    registry = link_source(registry, catalog, provider="osm", source_ref="way/900000002",
                           item_id=catalog.items[0].item_id)
    payload = json.loads(UPDATE.read_text())
    payload["elements"] = [payload["elements"][0]]
    result = sync_osm_snapshot(payload, base_catalog=catalog,
                               registry=registry, synthetic_fixture=True)
    assert result.decisions[0].status == "review"
    assert result.catalog == catalog


def test_partial_output_and_overwrite_protection(tmp_path, previous):
    catalog, registry = previous
    result = sync_osm_snapshot(json.loads(UPDATE.read_text()), base_catalog=catalog,
                               registry=registry, synthetic_fixture=True)
    paths = [tmp_path / f"file{i}.json" for i in range(3)]
    paths[1].write_text("exists", encoding="utf-8")
    with pytest.raises(IngestionError, match="already exists"):
        write_osm_sync(result, catalog_path=paths[0], registry_path=paths[1],
                       report_path=paths[2])
    assert not paths[0].exists() and not paths[2].exists()
    with pytest.raises(IngestionError, match="distinct"):
        write_osm_sync(result, catalog_path=paths[0], registry_path=paths[0],
                       report_path=paths[2])
    write_osm_sync(result, catalog_path=paths[0], registry_path=paths[1],
                   report_path=paths[2], overwrite=True)
    assert all(p.exists() for p in paths)
    assert load_registry(paths[1], load_catalog(paths[0])) == result.registry
    assert json.loads(paths[2].read_text())["osm_sync_schema_version"] == 1


def test_cli_bootstrap_sync_and_link(tmp_path, capsys):
    imported = import_osm_snapshot(json.loads(FIXTURE.read_text()), synthetic_fixture=True)
    catpath, reportpath = tmp_path / "catalog.json", tmp_path / "original.json"
    catpath.write_text(json.dumps(catalog_to_dict(imported.catalog)))
    reportpath.write_text(json.dumps(imported.report()))
    registry = tmp_path / "registry.json"
    assert main(["identity", "bootstrap-osm", "--catalog", str(catpath),
                 "--report", str(reportpath), "--output", str(registry)]) == 0
    assert len(json.loads(registry.read_text())["bindings"]) == 3
    outcat, outreg, outreport = (tmp_path / f"result-{n}.json" for n in (1, 2, 3))
    assert main(["osm", "sync", "--input", str(UPDATE), "--catalog", str(catpath),
                 "--registry", str(registry), "--synthetic-fixture",
                 "--output", str(outcat), "--registry-output", str(outreg),
                 "--report", str(outreport)]) == 0
    assert "'admitted': 1" in capsys.readouterr().out
    linked = tmp_path / "linked.json"
    canonical_id = imported.catalog.items[0].item_id
    assert main(["identity", "link", "--catalog", str(outcat),
                 "--registry", str(outreg), "--provider", "guide",
                 "--source-ref", "local-42", "--item-id", canonical_id,
                 "--output", str(linked)]) == 0
    assert load_registry(linked, load_catalog(outcat)).lookup("guide", "local-42")


def test_manual_catalog_edit_is_not_overwritten(previous):
    catalog, registry = previous
    modified = replace(catalog.items[0], description="Curator-maintained description")
    changed = Catalog(1, catalog.dataset_name, True, (modified, *catalog.items[1:]))
    payload = json.loads(UPDATE.read_text())
    payload["elements"] = [payload["elements"][0]]
    result = sync_osm_snapshot(payload, base_catalog=changed,
                               registry=registry, synthetic_fixture=True)
    assert result.decisions[0].status == "review"
    assert "differs" in result.decisions[0].reason
    assert result.catalog == changed


def test_cross_provider_link_does_not_disable_osm_update(previous):
    catalog, registry = previous
    registry = link_source(registry, catalog, provider="guide", source_ref="guide:17",
                           item_id=catalog.items[0].item_id)
    payload = json.loads(UPDATE.read_text())
    payload["elements"] = [payload["elements"][0]]
    result = sync_osm_snapshot(payload, base_catalog=catalog,
                               registry=registry, synthetic_fixture=True)
    assert result.decisions[0].status == "updated"
    assert result.registry.lookup("guide", "guide:17").item_id == catalog.items[0].item_id


def test_unknown_source_with_matching_name_and_location_is_reviewed(previous):
    catalog, registry = previous
    raw = json.loads(FIXTURE.read_text())
    raw["elements"] = [copy.deepcopy(raw["elements"][0])]
    raw["elements"][0]["id"] = 900000009
    result = sync_osm_snapshot(raw, base_catalog=catalog,
                               registry=registry, synthetic_fixture=True)
    assert result.decisions[0].status == "review"
    assert result.decisions[0].candidates == (catalog.items[0].item_id,)
    assert result.catalog == catalog


def test_stale_registry_and_inconsistent_source_flags_rejected(previous):
    catalog, registry = previous
    payload = json.loads(UPDATE.read_text())
    with pytest.raises(IngestionError, match="fixture marker"):
        sync_osm_snapshot(payload, base_catalog=catalog, registry=registry)
    payload.pop("savoroute_fixture")
    with pytest.raises(IngestionError, match="fixture marker"):
        sync_osm_snapshot(payload, base_catalog=catalog,
                          registry=registry, synthetic_fixture=True)
    corrupt = EntityRegistry((replace(registry.bindings[0], item_id="missing"),))
    with pytest.raises(IngestionError, match="absent item"):
        sync_osm_snapshot({"savoroute_fixture": True, "elements": []},
                          base_catalog=catalog, registry=corrupt, synthetic_fixture=True)
