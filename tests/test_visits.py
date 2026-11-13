"""Deterministic, opt-in, metadata-only visit discovery and review regression tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from savoroute.cli import main
from savoroute.data.catalog import catalog_to_dict
from savoroute.ingestion.osm import import_osm_snapshot
from savoroute.visits.workflow import (
    VisitError,
    _distance,
    build_review_template,
    finalize_visits,
    load_visit_json,
    suggest_visits,
)

_ROOT = Path(__file__).parent.parent / "data" / "sample"


@pytest.fixture
def setup():
    osm = json.loads((_ROOT / "osm_overpass_fixture_versioned.json").read_text())
    catalog = import_osm_snapshot(osm, synthetic_fixture=True).catalog
    photos = json.loads((_ROOT / "visit_photo_metadata_fixture.json").read_text())
    return catalog, osm, photos


def test_metadata_only_visit_clustering(setup):
    catalog, osm, photos = setup
    bundle = suggest_visits(catalog, osm, photos)
    assert bundle["status"] == "unreviewed"
    assert [row["photo_count"] for row in bundle["clusters"]] == [2, 2, 1]
    assert bundle["clusters"][0]["candidates"][0]["title"] == "Juniper Table"
    assert bundle["clusters"][1]["candidates"][0]["title"] == "Coastal Bowl"
    assert bundle["clusters"][2]["candidates"] == []
    assert bundle["clusters"][0]["started_at"] == "2026-01-04T17:00:00Z"
    assert not any("path" in key or "filename" in key for key in bundle)
    assert "source" not in bundle  # does not copy the OSM snapshot into personal history


def test_order_independence_and_timezone_equivalence(setup):
    catalog, osm, photos = setup
    expected = suggest_visits(catalog, osm, photos)
    photos["photos"].reverse()
    assert suggest_visits(catalog, osm, photos)["clusters"] == expected["clusters"]
    photos["photos"][0]["taken_at"] = "2026-01-05T15:00:00Z"
    assert suggest_visits(catalog, osm, photos)["clusters"] == expected["clusters"]


def test_photo_time_gap_splits_anchored_clusters(setup):
    catalog, osm, photos = setup
    photographs = photos["photos"][:2]
    photographs[1]["taken_at"] = "2026-01-04T15:50:00-05:00"
    photos["photos"] = photographs
    assert len(suggest_visits(catalog, osm, photos)["clusters"]) == 2


def test_gap_spanning_across_midnight_is_utc_safe(setup):
    catalog, osm, photos = setup
    photos["photos"] = photos["photos"][:2]
    photos["photos"][0]["taken_at"] = "2026-11-01T01:45:00-04:00"
    photos["photos"][1]["taken_at"] = "2026-11-01T01:15:00-05:00"
    result = suggest_visits(catalog, osm, photos)
    assert len(result["clusters"]) == 1
    assert result["clusters"][0]["started_at"] < result["clusters"][0]["ended_at"]


def test_near_dateline_not_world_away():
    assert _distance(0.0, 179.9999, 0.0, -179.9999) < 25
    assert _distance(42.35, -71.06, 42.35, -71.06) == 0
    assert _distance(0, 0, 0, 180) > 20_000_000


@pytest.mark.parametrize("field,value", [
    ("latitude", True), ("latitude", 91.0), ("longitude", -181.0),
    ("latitude", float("nan")), ("longitude", float("inf")),
    ("taken_at", "2026-01-04T12:00:00"), ("taken_at", "not a date"),
    ("photo_id", "../photo.png"),
])
def test_reject_invalid_photo_metadata(setup, field, value):
    catalog, osm, photos = setup
    photos["photos"][0][field] = value
    with pytest.raises(VisitError):
        suggest_visits(catalog, osm, photos)


def test_consent_explicit_no_raw_files_and_deduplicated_ids(setup):
    catalog, osm, photos = setup
    photos["user_selected"] = False
    with pytest.raises(VisitError, match="user-selected"):
        suggest_visits(catalog, osm, photos)
    photos["user_selected"] = True
    photos["photos"].append(copy.deepcopy(photos["photos"][0]))
    with pytest.raises(VisitError, match="unique"):
        suggest_visits(catalog, osm, photos)
    photos["photos"].pop()
    photos["photos"][0]["photo_path"] = "/home/user/Pictures/private.jpg"
    with pytest.raises(VisitError, match="exactly"):
        suggest_visits(catalog, osm, photos)


@pytest.mark.parametrize("parameter,value", [
    ("gap_minutes", 0), ("span_minutes", 721),
    ("cluster_radius_m", 1_001), ("match_radius_m", True),
    ("max_candidates", 21),
])
def test_reject_invalid_bounds(setup, parameter, value):
    catalog, osm, photos = setup
    with pytest.raises(VisitError):
        suggest_visits(catalog, osm, photos, **{parameter: value})


def test_source_binding_excludes_unadmitted_and_catalog_rewrites(setup):
    catalog, osm, photos = setup
    positions = {p["title"] for c in suggest_visits(catalog, osm, photos)["clusters"]
                 for p in c["candidates"]}
    assert positions == {"Juniper Table", "Coastal Bowl"}
    # A source ID cannot be silently matched to a different catalog title.
    edited = catalog_to_dict(catalog)
    edited["items"][0]["title"] = "Substituted name"
    from savoroute.data.catalog import parse_catalog
    with pytest.raises(VisitError, match="identity"):
        suggest_visits(parse_catalog(edited), osm, photos)


def _completed_review(bundle, decision_catalog):
    review = build_review_template(bundle)
    first, second, third = review["decisions"]
    first.update({"decision": "confirm", "item_id": bundle["clusters"][0]["candidates"][0]["item_id"],
                  "reason": "I visited this restaurant", "reviewed_on": "2026-01-06"})
    second.update({"decision": "reassign", "item_id": decision_catalog,
                   "reason": "My original location pin was imprecise", "reviewed_on": "2026-01-06"})
    third.update({"decision": "reject", "item_id": None,
                  "reason": "This was not a restaurant visit", "reviewed_on": "2026-01-06"})
    return review


def test_review_full_lifecycle_minimal_confirmed_history(setup):
    catalog, osm, photos = setup
    bundle = suggest_visits(catalog, osm, photos)
    # Reassign Coastal Bowl to another (non-candidate) restaurant.
    other = bundle["clusters"][0]["candidates"][0]["item_id"]
    review = _completed_review(bundle, other)
    output = finalize_visits(catalog, bundle, review)
    assert output["reviewed_count"] == 3
    assert output["rejected_count"] == 1
    assert [r["decision"] for r in output["confirmed_visits"]] == ["confirm", "reassign"]
    text = json.dumps(output)
    assert "latitude" not in text and "longitude" not in text
    assert "demo_a" not in text and "reason" not in text
    assert "User-confirmed" in output["limitations"]


def test_no_automatic_confirmation_or_guessing(setup):
    catalog, osm, photos = setup
    bundle = suggest_visits(catalog, osm, photos)
    review = build_review_template(bundle)
    with pytest.raises(VisitError, match="confirmed, rejected, or reassigned"):
        finalize_visits(catalog, bundle, review)
    assert all(row["decision"] is None and row["item_id"] is None for row in review["decisions"])


def test_unmatched_visit_can_be_explicitly_reassigned(setup):
    catalog, osm, photos = setup
    bundle = suggest_visits(catalog, osm, photos)
    review = build_review_template(bundle)
    for row in review["decisions"]:
        row.update({"decision": "reject", "item_id": None, "reason": "No visit", "reviewed_on": "2026-01-06"})
    last = review["decisions"][-1]
    last.update({"decision": "reassign", "item_id": catalog.items[0].item_id,
                 "reason": "User explicitly verified another venue", "reviewed_on": "2026-01-06"})
    result = finalize_visits(catalog, bundle, review)
    assert result["confirmed_visits"][0]["item_id"] == catalog.items[0].item_id
    assert result["rejected_count"] == 2


def test_stale_catalog_rejected(setup):
    catalog, osm, photos = setup
    bundle = suggest_visits(catalog, osm, photos)
    review = build_review_template(bundle)
    from savoroute.data.catalog import parse_catalog
    changed = catalog_to_dict(catalog)
    changed["items"][0]["description"] += " Edited"
    with pytest.raises(VisitError, match="different catalog"):
        finalize_visits(parse_catalog(changed), bundle, review)


def test_modified_bundle_or_review_digest_rejected(setup):
    catalog, osm, photos = setup
    bundle = suggest_visits(catalog, osm, photos)
    review = build_review_template(bundle)
    review["decisions"][0]["decision"] = "reject"
    modified = copy.deepcopy(bundle)
    modified["clusters"][0]["photo_count"] += 1
    with pytest.raises(VisitError, match="review does not match"):
        finalize_visits(catalog, modified, review)


def test_reassign_requires_distinct_item_and_confirm_must_be_candidate(setup):
    catalog, osm, photos = setup
    bundle = suggest_visits(catalog, osm, photos)
    review = build_review_template(bundle)
    for row in review["decisions"]:
        row.update({"decision": "reject", "item_id": None, "reason": "No visit", "reviewed_on": "2026-01-06"})
    review["decisions"][0].update({"decision": "reassign", "item_id": bundle["clusters"][0]["candidates"][0]["item_id"]})
    with pytest.raises(VisitError, match="different restaurant"):
        finalize_visits(catalog, bundle, review)
    review["decisions"][0].update({"decision": "confirm", "item_id": catalog.items[1].item_id})
    with pytest.raises(VisitError, match="nearby"):
        finalize_visits(catalog, bundle, review)


def test_no_overwrite_or_partial_outputs_cli(setup, tmp_path: Path, capsys):
    catalog, osm, photos = setup
    catalog_path = tmp_path / "catalog.json"
    osm_path = tmp_path / "osm.json"
    photo_path = tmp_path / "photos.json"
    catalog_path.write_text(json.dumps(catalog_to_dict(catalog)))
    osm_path.write_text(json.dumps(osm))
    photo_path.write_text(json.dumps(photos))
    proposals = tmp_path / "suggestions.json"
    review = tmp_path / "review.json"
    args = ["visits", "suggest", "--catalog", str(catalog_path), "--osm", str(osm_path),
            "--photos", str(photo_path), "--output", str(proposals),
            "--review-template", str(review)]
    review.write_text("existing")
    assert main(args) == 2
    assert not proposals.exists() and review.read_text() == "existing"
    review.unlink()
    assert main(args) == 0
    assert "unreviewed visit clusters" in capsys.readouterr().out
    assert json.loads(proposals.read_text())["status"] == "unreviewed"
    assert main(args) == 2
    assert "Error:" in capsys.readouterr().err
    sheet = json.loads(review.read_text())
    sheet["decisions"] = [
        {**row, "decision": "reject", "reason": "not a visit", "reviewed_on": "2026-01-06"}
        for row in sheet["decisions"]
    ]
    review.write_text(json.dumps(sheet))
    output = tmp_path / "confirmed.json"
    assert main(["visits", "finalize", "--catalog", str(catalog_path),
                 "--suggestions", str(proposals), "--review", str(review),
                 "--output", str(output)]) == 0
    assert json.loads(output.read_text())["rejected_count"] == 3
    assert main(["visits", "finalize", "--catalog", str(catalog_path),
                 "--suggestions", str(proposals), "--review", str(review),
                 "--output", str(output)]) == 2


def test_sample_metadata_does_not_reference_real_photos():
    source = (_ROOT / "visit_photo_metadata_fixture.json").read_text()
    assert "user_selected" in source
    assert "/home/" not in source
    assert ".jpg" not in source and ".png" not in source


def test_bounded_reader_rejects_oversized_input(tmp_path: Path):
    file = tmp_path / "private.json"
    file.write_bytes(b"0" * 512_001)
    with pytest.raises(VisitError, match="512 KB"):
        load_visit_json(file)
