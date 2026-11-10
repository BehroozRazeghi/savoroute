"""OSM snapshot import and bounded network request contract (all network calls mocked)."""

import json
from pathlib import Path

import pytest

from savoroute.cli import main
from savoroute.data.catalog import load_catalog
from savoroute.ingestion.osm import (
    MAX_RESPONSE_BYTES,
    fetch_overpass,
    import_osm_snapshot,
    overpass_query,
    validate_bbox,
    write_osm_import,
    write_overpass_snapshot,
)
from savoroute.ingestion.sources import IngestionError

FIXTURE = Path(__file__).resolve().parents[1] / "data/sample/osm_overpass_fixture.json"


@pytest.fixture
def snapshot():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_import_reports_review_and_skips(snapshot):
    result = import_osm_snapshot(snapshot, synthetic_fixture=True)
    states = [d.status for d in result.decisions]
    assert states == ["admitted", "review", "admitted", "skipped", "skipped", "admitted"]
    assert len(result.catalog.items) == 3
    assert result.catalog.synthetic
    assert all(x.source_url is None for x in result.catalog.items)
    assert result.catalog.items[0].cuisines == ("italian", "pizza")
    assert result.catalog.items[0].dietary_tags == ()
    assert result.decisions[1].candidate_ids == (result.catalog.items[0].item_id,)
    assert result.report()["admitted_sources"][0]["source_tags"]["name"] == "Juniper Table"
    assert result.report()["licence"] is None


def test_stable_ids_and_repeat_import(snapshot):
    first = import_osm_snapshot(snapshot, synthetic_fixture=True)
    repeat = import_osm_snapshot(snapshot, base_catalog=first.catalog, synthetic_fixture=True)
    assert len(repeat.catalog.items) == 3
    assert [d.status for d in repeat.decisions].count("already_imported") == 3
    assert repeat.catalog == first.catalog


def test_real_data_attribution(snapshot):
    snapshot.pop("savoroute_fixture")
    result = import_osm_snapshot(snapshot)
    assert result.report()["licence"] == "ODbL-1.0"
    assert result.catalog.items[0].source_url == "https://www.openstreetmap.org/node/900000001"
    assert not result.catalog.synthetic


def test_reject_mixing_demo_and_real(snapshot):
    snapshot.pop("savoroute_fixture")
    with pytest.raises(IngestionError, match="synthetic flag"):
        import_osm_snapshot(snapshot, base_catalog=load_catalog())


def test_bad_elements(snapshot):
    for field in ("elements",):
        invalid = {"version": 0.6}
        with pytest.raises(IngestionError, match=field):
            import_osm_snapshot(invalid)
    snapshot["elements"].append(snapshot["elements"][0])
    with pytest.raises(IngestionError, match="duplicate OSM"):
        import_osm_snapshot(snapshot, synthetic_fixture=True)


def test_overpass_error_remark(snapshot):
    snapshot["remark"] = "runtime error"
    with pytest.raises(IngestionError, match="remark"):
        import_osm_snapshot(snapshot)


def test_invalid_type_and_geometry(snapshot):
    snapshot["elements"][0]["id"] = True
    snapshot["elements"][2]["lat"] = "invalid"
    result = import_osm_snapshot(snapshot, synthetic_fixture=True)
    assert result.decisions[0].status == "skipped"
    assert result.decisions[2].status == "admitted"  # valid city remains
    assert len(result.catalog.items) == 3


def test_bbox_limits_and_query():
    with pytest.raises(IngestionError, match="bbox"):
        validate_bbox((42.4, -71.2, 42.3, -71.1))
    with pytest.raises(IngestionError, match="span"):
        validate_bbox((42.3, -71.2, 43.0, -71.1))
    query = overpass_query((42.3, -71.2, 42.31, -71.19))
    assert "nwr" in query and "out center;" in query
    assert "42.3000000,-71.2000000,42.3100000,-71.1900000" in query


def test_fetch_mocked(monkeypatch):
    from savoroute.ingestion import osm
    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def read(self, n):
            assert n == MAX_RESPONSE_BYTES + 1
            return b'{"elements": []}'
    def fake_urlopen(request, timeout):
        assert request.full_url == osm.OVERPASS_ENDPOINT
        assert request.get_method() == "POST"
        assert "Savoroute" in request.get_header("User-agent")
        assert "amenity" in request.data.decode()
        assert timeout <= 35
        return FakeResponse()
    monkeypatch.setattr(osm, "urlopen", fake_urlopen)
    assert fetch_overpass((42.3, -71.2, 42.31, -71.19), contact="dev@example.org") == {"elements": []}
    with pytest.raises(IngestionError, match="contact"):
        fetch_overpass((42.3, -71.2, 42.31, -71.19), contact="not-an-email")


def test_mocked_server_too_large(monkeypatch):
    from savoroute.ingestion import osm
    class BigResponse:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def read(self, n):
            return b"x" * n
    monkeypatch.setattr(osm, "urlopen", lambda request, timeout: BigResponse())
    with pytest.raises(IngestionError, match="2 MB"):
        fetch_overpass((42.3, -71.2, 42.31, -71.19), contact="dev@example.org")


def test_snapshot_and_outputs(tmp_path, snapshot):
    raw = tmp_path / "raw.json"
    write_overpass_snapshot(snapshot, raw)
    with pytest.raises(IngestionError, match="already exists"):
        write_overpass_snapshot(snapshot, raw)
    result = import_osm_snapshot(snapshot, synthetic_fixture=True)
    catalog, report = tmp_path / "catalog.json", tmp_path / "report.json"
    write_osm_import(result, catalog_path=catalog, report_path=report)
    assert len(load_catalog(catalog).items) == 3
    assert len(json.loads(report.read_text())["decisions"]) == 6
    with pytest.raises(IngestionError, match="already exists"):
        write_osm_import(result, catalog_path=catalog, report_path=report)


def test_cli_osm_fixture(tmp_path, capsys):
    output, report = tmp_path / "catalog.json", tmp_path / "report.json"
    assert main(["osm", "import", "--input", str(FIXTURE), "--synthetic-fixture",
                 "--output", str(output), "--report", str(report)]) == 0
    assert "'review': 1" in capsys.readouterr().out
    assert main(["validate", "--catalog", str(output)]) == 0
    assert "items=3" in capsys.readouterr().out
    assert main(["search", "juniper", "--catalog", str(output)]) == 0


def test_fixture_marker_prevents_false_live_attribution(snapshot):
    with pytest.raises(IngestionError, match="fixture marker"):
        import_osm_snapshot(snapshot)
    snapshot.pop("savoroute_fixture")
    with pytest.raises(IngestionError, match="fixture marker"):
        import_osm_snapshot(snapshot, synthetic_fixture=True)


def test_review_against_base_catalog(snapshot):
    base = import_osm_snapshot(snapshot, synthetic_fixture=True).catalog
    candidate = snapshot["elements"][0].copy()
    candidate["id"] = 900000010
    batch = {"savoroute_fixture": True, "elements": [candidate]}
    result = import_osm_snapshot(batch, base_catalog=base, synthetic_fixture=True)
    assert result.decisions[0].status == "review"
    assert result.decisions[0].candidate_ids == (base.items[0].item_id,)
    assert result.catalog == base
