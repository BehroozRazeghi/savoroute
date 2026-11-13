"""Software-method tests, not real-world retrieval evidence.

All study inputs and judgments here are fictional and assigned solely to
exercise the validation and paired statistical code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from savoroute.cli import main
from savoroute.data.catalog import catalog_to_dict
from savoroute.evaluation.research import (
    _paired_bootstrap,
    analyze_reviewed_study,
    audit_reviewer_progress,
    prepare_analysis_plan,
)
from savoroute.evaluation.study import StudyError, prepare_osm_study
from savoroute.ingestion.osm import import_osm_snapshot

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _scenario(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    source = SAMPLE / "osm_overpass_fixture.json"
    imported = import_osm_snapshot(json.loads(source.read_text()), synthetic_fixture=True)
    catalog = _write(tmp_path / "catalog.json", catalog_to_dict(imported.catalog))
    queries = {
        "query_set_version": 1,
        "queries": [
            {"case_id": f"{split}{i}", "query": f"{name} restaurant {split}",
             "filters": {}, "split": split}
            for split in ("development", "test")
            for i, name in enumerate(("Italian", "Mediterranean", "Mexican", "Vegan"), 1)
        ],
    }
    qs = _write(tmp_path / "queries.json", queries)
    root = tmp_path / "frozen"
    prepare_osm_study(
        source_path=source, catalog_path=catalog, queries_path=qs, output_dir=root,
        collected_at="2026-11-12T14:00:00Z",
        selection_protocol="Fully fictional source, fixed for software regression",
        query_protocol="Eight fictional hard-coded queries with fixed dev/test split",
        allow_synthetic_fixture=True,
    )
    a = json.loads((root / "reviewer_a.json").read_text())
    b = json.loads((root / "reviewer_b.json").read_text())
    return root, catalog, _write(tmp_path / "a.json", a), _write(tmp_path / "b.json", b), qs


def _completed(root: Path, workbook_path: Path) -> Path:
    template = json.loads((root / "review_template.json").read_text())
    first = json.loads((root / "catalog.json").read_text())["items"][0]["item_id"]
    for row in template["judgments"]:
        # dev/test query 1 and 2 each have one *fictionally assigned* positive.
        positive = row["case_id"][-1] in "12" and row["item_id"] == first
        row["reviews"] = {"reviewer_a": positive, "reviewer_b": positive}
        row["reviewer_notes"] = {
            "reviewer_a": "Fixture-only judgment" if positive else "",
            "reviewer_b": "Fixture-only judgment" if positive else "",
        }
        row["final_label"] = positive
    return _write(workbook_path, template)


def test_partial_audit_and_safe_counts(tmp_path: Path):
    root, _, a, b, _ = _scenario(tmp_path)
    blank = audit_reviewer_progress(root, a, b)
    assert blank["overall"]["pairs"] == 24
    assert blank["overall"]["both_complete"] == 0
    assert blank["annotation_status"] == "review_incomplete"
    assert "judgments" not in blank
    a_doc = json.loads(a.read_text())
    b_doc = json.loads(b.read_text())
    a_doc["judgments"][0].update(relevant=True, note="Fixture-only rationale")
    b_doc["judgments"][0].update(relevant=False, note="Not supported by fixture")
    _write(a, a_doc)
    _write(b, b_doc)
    audit = audit_reviewer_progress(root, a, b)
    assert audit["overall"]["both_complete"] == 1
    assert audit["overall"]["disagreements_on_both_complete"] == 1
    assert audit["partitions"]["development"]["pairs"] == 12
    assert audit["partitions"]["test"]["pairs"] == 12
    assert not audit["overall"]["ready_to_merge"]
    assert "Fixture-only rationale" not in json.dumps(audit)


def test_reviewer_boundaries_and_rationale(tmp_path: Path):
    root, _, a, b, _ = _scenario(tmp_path)
    record = json.loads(a.read_text())
    record["catalog_sha256"] = "0" * 64
    _write(a, record)
    with pytest.raises(StudyError, match="identity"):
        audit_reviewer_progress(root, a, b)
    record = json.loads((root / "reviewer_a.json").read_text())
    record["judgments"][0]["relevant"] = True
    _write(a, record)
    with pytest.raises(StudyError, match="rationale"):
        audit_reviewer_progress(root, a, b)
    record["judgments"][0]["note"] = "Explicit fictional rationale"
    record["judgments"][1] = dict(record["judgments"][0])
    _write(a, record)
    with pytest.raises(StudyError, match="duplicate"):
        audit_reviewer_progress(root, a, b)


def test_reviewer_completion_and_disagreements(tmp_path: Path):
    root, _, a, b, _ = _scenario(tmp_path)
    for path in (a, b):
        payload = json.loads(path.read_text())
        for row in payload["judgments"]:
            row["relevant"] = False
            row["note"] = ""
        _write(path, payload)
    report = audit_reviewer_progress(root, a, b)
    assert report["overall"]["ready_to_merge"] is True
    assert report["annotation_status"] == "review_sheets_complete_not_adjudicated"
    assert report["overall"]["disagreements_on_both_complete"] == 0


def test_plan_is_deterministic_bound_and_non_overwriting(tmp_path: Path):
    root, _, _, _, _ = _scenario(tmp_path)
    path = tmp_path / "plan.json"
    plan = prepare_analysis_plan(root, path, resamples=250, seed=17)
    assert plan["at_k"] == 5
    assert plan["primary_metric"] == "ndcg_at_k"
    assert plan["baselines"] == ["bm25", "overlap"]
    with pytest.raises(ValueError, match="already exists"):
        prepare_analysis_plan(root, path, resamples=250, seed=17)
    second = tmp_path / "other.json"
    assert prepare_analysis_plan(root, second, resamples=250, seed=17) == plan
    assert second.read_bytes() == path.read_bytes()
    with pytest.raises(StudyError, match="resamples"):
        prepare_analysis_plan(root, tmp_path / "bad.json", resamples=199)
    with pytest.raises(StudyError, match="primary_metric"):
        prepare_analysis_plan(root, tmp_path / "bad.json", primary_metric="precision")


def test_analysis_requires_labels_and_test_release(tmp_path: Path):
    root, _, _, _, _ = _scenario(tmp_path)
    plan = tmp_path / "plan.json"
    prepare_analysis_plan(root, plan, resamples=300, seed=123)
    unfinished = root / "review_template.json"
    with pytest.raises(ValueError, match="unfinished"):
        analyze_reviewed_study(root, unfinished, plan)
    workbook = _completed(root, tmp_path / "adjudicated.json")
    with pytest.raises(StudyError, match="allow_test"):
        analyze_reviewed_study(root, workbook, plan, split="test")
    dev = analyze_reviewed_study(root, workbook, plan)
    test = analyze_reviewed_study(root, workbook, plan, split="test", allow_test=True)
    assert dev["study_report"]["split"] == "development"
    assert test["study_report"]["split"] == "test"
    assert dev["metrics"]["ndcg_at_k"]["n_queries"] == 2
    assert dev["metrics"]["correct_empty"]["n_queries"] == 2
    assert dev["metrics"]["ndcg_at_k"]["bm25_minus_overlap"]["ci95"] is not None
    assert len(dev["query_errors"]["bm25"]) == 4
    assert all("case_id" in x for x in dev["query_errors"]["bm25"])
    assert dev["bootstrap"]["unit"] == "query"
    assert dev == analyze_reviewed_study(root, workbook, plan)


def test_analysis_study_and_plan_tampering(tmp_path: Path):
    root, _, _, _, _ = _scenario(tmp_path)
    plan_path = tmp_path / "plan.json"
    prepare_analysis_plan(root, plan_path, resamples=250)
    workbook = _completed(root, tmp_path / "workbook.json")
    plan = json.loads(plan_path.read_text())
    plan["queries_sha256"] = "f" * 64
    _write(plan_path, plan)
    with pytest.raises(StudyError, match="does not match"):
        analyze_reviewed_study(root, workbook, plan_path)
    prepare_analysis_plan(root, tmp_path / "valid.json", resamples=250)
    payload = json.loads(workbook.read_text())
    payload["queries"][0]["query"] = "Altered query"
    _write(workbook, payload)
    with pytest.raises(StudyError, match="frozen"):
        analyze_reviewed_study(root, workbook, tmp_path / "valid.json")


def test_pair_bootstrap_known_cases():
    identical = _paired_bootstrap([0.0, 1.0, 0.5], [0.0, 1.0, 0.5],
                                  resamples=200, seed=4, metric="same")
    assert identical["estimate"] == 0.0
    assert identical["ci95"] == [0.0, 0.0]
    positive = _paired_bootstrap([1.0, 1.0], [0.0, 0.0],
                                 resamples=200, seed=4, metric="positive")
    assert positive["estimate"] == 1.0
    assert positive["ci95"] == [1.0, 1.0]
    assert _paired_bootstrap([], [], resamples=200, seed=3, metric="none")["ci95"] is None
    assert _paired_bootstrap([0.5], [0.2], resamples=200, seed=3,
                             metric="one")["ci95"] is None
    assert _paired_bootstrap([1.0, 0.0], [0.0, 1.0], resamples=200,
                             seed=3, metric="pair") == _paired_bootstrap(
        [1.0, 0.0], [0.0, 1.0], resamples=200, seed=3, metric="pair"
    )
    with pytest.raises(StudyError, match="paired"):
        _paired_bootstrap([1.0], [1.0, 0.0], resamples=200, seed=3, metric="bad")


def test_cli_workflow_audit_plan_analyze(tmp_path: Path, capsys):
    root, _, a, b, _ = _scenario(tmp_path)
    assert main(["study", "audit", "--study-dir", str(root),
                 "--reviewer-a", str(a), "--reviewer-b", str(b)]) == 0
    assert '"review_incomplete"' in capsys.readouterr().out
    plan = tmp_path / "plan.json"
    assert main(["study", "plan", "--study-dir", str(root), "--output", str(plan),
                 "--resamples", "200"]) == 0
    workbook = _completed(root, tmp_path / "workbook.json")
    out = tmp_path / "report.json"
    argv = ["study", "analyze", "--study-dir", str(root), "--plan", str(plan),
            "--workbook", str(workbook), "--split", "test", "--output", str(out)]
    assert main(argv) == 2
    assert "allow_test" in capsys.readouterr().err
    assert main(argv + ["--allow-test"]) == 0
    assert json.loads(out.read_text())["metrics"]["recall_at_k"]["n_queries"] == 2
    assert main(argv + ["--allow-test"]) == 2  # never overwrite report


def test_undefined_primary_metric_is_not_reported(tmp_path: Path):
    root, _, _, _, _ = _scenario(tmp_path)
    plan_file = tmp_path / "plan.json"
    prepare_analysis_plan(root, plan_file, resamples=200)
    workbook = _completed(root, tmp_path / "workbook.json")
    data = json.loads(workbook.read_text())
    for row in data["judgments"]:
        row["reviews"] = {"reviewer_a": False, "reviewer_b": False}
        row["reviewer_notes"] = {"reviewer_a": "", "reviewer_b": ""}
        row["final_label"] = False
    _write(workbook, data)
    with pytest.raises(StudyError, match="primary metric is undefined"):
        analyze_reviewed_study(root, workbook, plan_file)
