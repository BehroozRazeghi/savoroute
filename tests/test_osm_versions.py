"""Version ordering and registry schema migration regressions."""

import copy
import json
from pathlib import Path

import pytest

from savoroute.identity.osm_versions import validate_osm_metadata
from savoroute.identity.registry import (
    SourceBinding,
    bootstrap_osm_registry,
    parse_registry,
)
from savoroute.ingestion.osm import import_osm_snapshot, overpass_query
from savoroute.ingestion.sources import IngestionError
from savoroute.services.osm_sync import sync_osm_snapshot

INITIAL = Path("data/sample/osm_overpass_fixture_versioned.json")
UPDATED = Path("data/sample/osm_overpass_update_fixture_versioned.json")


def data(path):
    return json.loads(path.read_text(encoding="utf-8"))


def initial():
    import_result = import_osm_snapshot(data(INITIAL), synthetic_fixture=True)
    return import_result.catalog, bootstrap_osm_registry(import_result.catalog,
                                                        import_result.report())


def single_update():
    row = data(UPDATED)["elements"][0]
    return {"savoroute_fixture": True, "elements": [row]}


def test_overpass_fetch_requests_element_metadata():
    query = overpass_query((42.30, -71.10, 42.31, -71.09))
    assert query.endswith("out center meta;")


def test_import_bootstrap_and_update_record_version():
    catalog, registry = initial()
    previous = registry.lookup("osm", "node/900000001")
    assert previous.source_version == 1
    assert previous.source_timestamp == "2026-01-01T10:00:00Z"
    assert len(previous.source_sha256) == 64
    assert registry.as_dict()["registry_schema_version"] == 2
    assert parse_registry(registry.as_dict(), catalog) == registry
    result = sync_osm_snapshot(single_update(), base_catalog=catalog, registry=registry,
                               synthetic_fixture=True)
    assert result.decisions[0].status == "updated"
    newer = result.registry.lookup("osm", "node/900000001")
    assert newer.source_version == 2
    assert newer.source_timestamp == "2026-01-02T10:00:00Z"
    repeated = sync_osm_snapshot(single_update(), base_catalog=result.catalog,
                                 registry=result.registry, synthetic_fixture=True)
    assert repeated.decisions[0].status == "unchanged"
    assert repeated.registry == result.registry


@pytest.mark.parametrize("mutate, expected", [
    (lambda row: row.update({"version": 1, "timestamp": "2026-01-01T10:00:00Z"}),
     "stale source version"),
    (lambda row: row.update({"tags": dict(row["tags"], cuisine="other")}),
     "same source version has different content"),
    (lambda row: row.update({"version": 3, "timestamp": "2026-01-02T10:00:00Z"}),
     "non-increasing timestamp"),
    (lambda row: (row.pop("version"), row.pop("timestamp")), "version missing"),
    (lambda row: row.update({"timestamp": "2026-05-77T00:00:00Z"}),
     "valid UTC datetime"),
])
def test_reject_older_inconsistent_or_missing_versions(mutate, expected):
    catalog, registry = initial()
    first = sync_osm_snapshot(single_update(), base_catalog=catalog, registry=registry,
                              synthetic_fixture=True)
    snapshot = single_update()
    mutate(snapshot["elements"][0])
    second = sync_osm_snapshot(snapshot, base_catalog=first.catalog,
                               registry=first.registry, synthetic_fixture=True)
    assert second.decisions[0].status == "review"
    assert expected in second.decisions[0].reason
    assert second.catalog == first.catalog
    assert second.registry == first.registry


def test_upgrade_v1_registry_without_version_baseline():
    catalog, registry = initial()
    old = registry.as_dict()
    old["registry_schema_version"] = 1
    for row in old["bindings"]:
        del row["source_version"]
        del row["source_timestamp"]
    loaded = parse_registry(old, catalog)
    assert loaded.lookup("osm", "node/900000001").source_version is None
    assert loaded.as_dict()["registry_schema_version"] == 2
    first = sync_osm_snapshot(single_update(), base_catalog=catalog,
                              registry=loaded, synthetic_fixture=True)
    assert first.decisions[0].status == "updated"
    assert first.registry.lookup("osm", "node/900000001").source_version == 2


def test_bootstrap_accepts_v1_import_report():
    imported = import_osm_snapshot(data(INITIAL), synthetic_fixture=True)
    old_report = copy.deepcopy(imported.report())
    old_report["osm_import_schema_version"] = 1
    for entry in old_report["admitted_sources"]:
        for name in ("source_sha256", "source_version", "source_timestamp"):
            entry.pop(name)
    registry = bootstrap_osm_registry(imported.catalog, old_report)
    assert registry.lookup("osm", "node/900000001").source_version is None


@pytest.mark.parametrize("version, timestamp", [
    (True, "2026-01-01T10:00:00Z"), (0, "2026-01-01T10:00:00Z"),
    (1, None), (None, "2026-01-01T10:00:00Z"),
    (1, "2026-02-30T10:00:00Z"), (1, "2026-01-01"),
    (1, "2026-01-01T10:00:00+02:00"),
])
def test_invalid_version_metadata(version, timestamp):
    with pytest.raises(IngestionError):
        validate_osm_metadata(version, timestamp)


def test_reject_metadata_on_non_osm_binding():
    with pytest.raises(IngestionError, match="only for OSM"):
        SourceBinding("guide", "store-1", "i_1", source_version=1,
                      source_timestamp="2026-01-01T10:00:00Z")


def test_non_versioned_backwards_compatibility():
    original = data(Path("data/sample/osm_overpass_fixture.json"))
    imported = import_osm_snapshot(original, synthetic_fixture=True)
    registry = bootstrap_osm_registry(imported.catalog, imported.report())
    assert registry.lookup("osm", "node/900000001").source_version is None
