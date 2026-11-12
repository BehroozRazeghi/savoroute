"""Reproducible study bundles and conservative evaluation gates."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from savoroute.cli import main
from savoroute.data.catalog import catalog_to_dict
from savoroute.evaluation.study import (
    StudyError,
    evaluate_reviewed_study,
    prepare_osm_study,
    verify_osm_study,
    write_study_report,
)
from savoroute.ingestion.osm import import_osm_snapshot

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"


def setup_fixture(tmp_path: Path) -> tuple[dict, Path, Path, Path]:
    source = SAMPLE / "osm_overpass_fixture.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    result = import_osm_snapshot(payload, synthetic_fixture=True)
    catalog_file = tmp_path / "catalog.json"
    catalog_file.write_text(json.dumps(catalog_to_dict(result.catalog)), encoding="utf-8")
    queries = {
        "query_set_version": 1,
        "queries": [
            {"case_id": "a", "query": "Italian restaurant", "filters": {},
             "split": "development"},
            {"case_id": "b", "query": "Mediterranean restaurant", "filters": {},
             "split": "test"},
        ],
    }
    query_file = tmp_path / "queries.json"
    query_file.write_text(json.dumps(queries), encoding="utf-8")
    parameters = dict(
        source_path=source, catalog_path=catalog_file, queries_path=query_file,
        output_dir=tmp_path / "study", collected_at="2026-11-12T14:00:00Z",
        selection_protocol="Fictional local importer fixture", query_protocol="Fictional queries",
        allow_synthetic_fixture=True,
    )
    return parameters, source, catalog_file, query_file


def test_frozen_study_and_review_reference(tmp_path: Path):
    parameters, *_ = setup_fixture(tmp_path)
    manifest = prepare_osm_study(**parameters)
    root = Path(parameters["output_dir"])
    assert manifest == verify_osm_study(root)
    assert manifest["items"] == 3
    assert manifest["synthetic"] is True
    assert len(json.loads((root / "review_reference.json").read_text())["records"]) == 6
    assert not any("score" in row for row in json.loads(
        (root / "review_reference.json").read_text()
    )["records"])
    assert all(row["relevant"] is None for row in json.loads(
        (root / "reviewer_a.json").read_text()
    )["judgments"])
    with pytest.raises(StudyError, match="already exists"):
        prepare_osm_study(**parameters)


@pytest.mark.parametrize("changed_file", ["source.json", "catalog.json", "queries.json",
                                           "review_reference.json", "reviewer_a.json"])
def test_detects_tampering(tmp_path: Path, changed_file: str):
    parameters, *_ = setup_fixture(tmp_path)
    prepare_osm_study(**parameters)
    target = Path(parameters["output_dir"]) / changed_file
    target.write_text(target.read_text() + " ", encoding="utf-8")
    with pytest.raises(StudyError, match="modified"):
        verify_osm_study(parameters["output_dir"])


def test_reject_synthetic_without_opt_in_and_mismatched_catalog(tmp_path: Path):
    parameters, _, catalog_file, _ = setup_fixture(tmp_path)
    with pytest.raises(StudyError, match="fictional datasets"):
        prepare_osm_study(**{**parameters, "allow_synthetic_fixture": False})
    catalog = json.loads(catalog_file.read_text())
    catalog["items"][0]["title"] = "Tampered name"
    catalog_file.write_text(json.dumps(catalog))
    with pytest.raises(StudyError, match="does not match"):
        prepare_osm_study(**parameters)


def test_reject_duplicate_normalized_queries(tmp_path: Path):
    parameters, _, _, query_file = setup_fixture(tmp_path)
    data = json.loads(query_file.read_text())
    data["queries"][1]["query"] = "ITALIAN, restaurant!"
    query_file.write_text(json.dumps(data))
    with pytest.raises(StudyError, match="duplicate normalized query"):
        prepare_osm_study(**parameters)


def test_non_fixture_study_path_is_structurally_supported(tmp_path: Path):
    # This exercise removes a fixture marker but is NOT real OSM data.
    parameters, source, catalog_file, _ = setup_fixture(tmp_path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload.pop("savoroute_fixture")
    raw_path = tmp_path / "non_fixture_snapshot.json"
    raw_path.write_text(json.dumps(payload), encoding="utf-8")
    imported = import_osm_snapshot(payload)
    catalog_file.write_text(json.dumps(catalog_to_dict(imported.catalog)), encoding="utf-8")
    manifest = prepare_osm_study(
        **{**parameters, "source_path": raw_path, "allow_synthetic_fixture": False},
    )
    assert manifest["synthetic"] is False
    assert manifest["source_decisions"]["admitted"] == 3
    assert verify_osm_study(parameters["output_dir"]) == manifest


def test_non_searchable_query_is_rejected(tmp_path: Path):
    parameters, _, _, query_file = setup_fixture(tmp_path)
    queries = json.loads(query_file.read_text())
    queries["queries"][0]["query"] = "!!!"
    query_file.write_text(json.dumps(queries))
    with pytest.raises(StudyError, match="no searchable text"):
        prepare_osm_study(**parameters)


def test_reject_invalid_time_and_invalid_protocol(tmp_path: Path):
    parameters, *_ = setup_fixture(tmp_path)
    with pytest.raises(StudyError, match="UTC"):
        prepare_osm_study(**{**parameters, "collected_at": "2026-11-12T14:00:00"})
    with pytest.raises(StudyError, match="query_protocol"):
        prepare_osm_study(**{**parameters, "query_protocol": " "})


def _reviewed_workbook(root: Path) -> dict:
    workbook = json.loads((root / "review_template.json").read_text())
    for index, pair in enumerate(workbook["judgments"]):
        decision = index == 0
        pair["reviews"] = {"reviewer_a": decision, "reviewer_b": decision}
        pair["reviewer_notes"] = {
            "reviewer_a": "Synthetic rationale" if decision else "",
            "reviewer_b": "Synthetic rationale" if decision else "",
        }
        pair["final_label"] = decision
    return workbook


def test_study_evaluation_requires_completed_labels_and_explicit_test_gate(tmp_path: Path):
    parameters, *_ = setup_fixture(tmp_path)
    prepare_osm_study(**parameters)
    root = Path(parameters["output_dir"])
    workbook_file = tmp_path / "reviewed.json"
    workbook_file.write_text(json.dumps(_reviewed_workbook(root)))
    report = evaluate_reviewed_study(root, workbook_file)
    assert report["split"] == "development"
    assert report["query_count"] == 1
    assert report["annotation_audit"]["synthetic"] is True
    assert set(report["systems"]) == {"bm25", "overlap"}
    assert report["systems"]["bm25"]["cases"][0]["case_id"] == "a"
    with pytest.raises(StudyError, match="allow_test"):
        evaluate_reviewed_study(root, workbook_file, split="test")
    assert evaluate_reviewed_study(root, workbook_file, split="test", allow_test=True)[
        "query_count"
    ] == 1
    report_file = tmp_path / "report.json"
    write_study_report(report, report_file)
    with pytest.raises(ValueError, match="already exists"):
        write_study_report(report, report_file)
    workbook = _reviewed_workbook(root)
    workbook["judgments"][0]["final_label"] = None
    workbook_file.write_text(json.dumps(workbook))
    with pytest.raises(ValueError, match="unfinished"):
        evaluate_reviewed_study(root, workbook_file)


def test_study_cli(tmp_path: Path, capsys):
    parameters, _, catalog_path, query_file = setup_fixture(tmp_path)
    args = [
        "study", "prepare-osm", "--source", str(parameters["source_path"]),
        "--catalog", str(catalog_path), "--queries", str(query_file),
        "--output-dir", str(parameters["output_dir"]),
        "--collected-at", parameters["collected_at"],
        "--selection-protocol", parameters["selection_protocol"],
        "--query-protocol", parameters["query_protocol"], "--synthetic-fixture",
    ]
    assert main(args) == 0
    assert main(["study", "verify", "--study-dir", str(parameters["output_dir"])]) == 0
    workbook = tmp_path / "reviewed.json"
    workbook.write_text(json.dumps(_reviewed_workbook(Path(parameters["output_dir"]))))
    assert main(["study", "evaluate", "--study-dir", str(parameters["output_dir"]),
                 "--workbook", str(workbook), "--split", "test"]) == 2
    assert "allow_test" in capsys.readouterr().err
    assert main(["study", "evaluate", "--study-dir", str(parameters["output_dir"]),
                 "--workbook", str(workbook), "--split", "test", "--allow-test"]) == 0
