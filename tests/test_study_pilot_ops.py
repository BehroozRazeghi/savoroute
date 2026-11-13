"""Fictional study-operations checks; none are real-world relevance labels."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from savoroute.data.catalog import catalog_to_dict
from savoroute.evaluation.research import analyze_reviewed_study, prepare_analysis_plan
from savoroute.evaluation.study import StudyError, prepare_osm_study
from savoroute.ingestion.osm import import_osm_snapshot
from scripts.study_pilot import (
    PilotError,
    _write_new,
    main,
    package_reviewers,
    preflight,
    summarize_analysis,
)

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample"


def _write(path: Path, obj: dict) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def _scenario(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = SAMPLE / "osm_overpass_fixture.json"
    fixture = json.loads(source.read_text())
    imported = import_osm_snapshot(fixture, synthetic_fixture=True)
    catalog = _write(tmp_path / "catalog.json", catalog_to_dict(imported.catalog))
    queries = {
        "query_set_version": 1,
        "queries": [
            {"case_id": f"{split}{i}", "query": f"{cuisine} restaurant {split}",
             "filters": {}, "split": split}
            for split in ("development", "test")
            for i, cuisine in enumerate(("Italian", "Chinese"), 1)
        ],
    }
    qs = _write(tmp_path / "queries.json", queries)
    root = tmp_path / "frozen"
    prepare_osm_study(
        source_path=source, catalog_path=catalog, queries_path=qs,
        output_dir=root, collected_at="2026-11-12T14:00:00Z",
        selection_protocol="Fictional source for regression tests",
        query_protocol="Four fictional fixed queries, two dev and two test",
        allow_synthetic_fixture=True,
    )
    plan = tmp_path / "analysis-plan.json"
    prepare_analysis_plan(root, plan, resamples=200)
    return root, plan, catalog


def test_preflight_is_label_free_and_bind_plan(tmp_path: Path):
    study, plan, _ = _scenario(tmp_path)
    result = preflight(study, plan_path=plan)
    assert result["synthetic"] is True
    assert result["study_status"] == "awaiting_independent_human_judgments"
    assert result["analysis_plan_sha256"]
    assert len(result["per_query"]) == 4
    assert sum(x["eligible_pairs"] for x in result["per_query"]) == result["judgment_pairs"]
    assert result["evidence_coverage"]["pairs_without_recorded_cuisine"] >= 0
    assert "judgments" not in result
    payload = json.loads(plan.read_text())
    payload["catalog_fingerprint"] = "bad"
    _write(plan, payload)
    with pytest.raises(PilotError, match="analysis plan"):
        preflight(study, plan_path=plan)


def test_two_reviewer_archives_are_separate_and_deterministic(tmp_path: Path):
    study, plan, _ = _scenario(tmp_path)
    out = tmp_path / "packages"
    result = package_reviewers(study, plan, out)
    assert set(result["archives"]) == {"reviewer_a", "reviewer_b"}
    for slot, other in (("reviewer_a", "reviewer_b"), ("reviewer_b", "reviewer_a")):
        with zipfile.ZipFile(out / f"{slot}.zip") as archive:
            names = set(archive.namelist())
            assert f"{slot}.json" in names
            assert f"{other}.json" not in names
            assert "source.json" in names
            assert "review_reference.json" in names
            assert not any("analysis" in name or "ranking" in name for name in names)
            sheet = json.loads(archive.read(f"{slot}.json"))
            assert all(row["relevant"] is None for row in sheet["judgments"])
            manifest = json.loads(archive.read("package-manifest.json"))
            assert manifest["reviewer_slot"] == slot
            assert "Missing OSM" in archive.read("INSTRUCTIONS.md").decode()
    with pytest.raises(PilotError, match="already exists"):
        package_reviewers(study, plan, out)
    # Rebuilding in another path produces the same bytes, including ZIP metadata.
    again = tmp_path / "repeat"
    package_reviewers(study, plan, again)
    for slot in ("reviewer_a", "reviewer_b"):
        assert (out / f"{slot}.zip").read_bytes() == (again / f"{slot}.zip").read_bytes()


def test_package_rejects_changed_frozen_source(tmp_path: Path):
    study, plan, _ = _scenario(tmp_path)
    (study / "queries.json").write_text('{"queries":[]}', encoding="utf-8")
    with pytest.raises(StudyError, match="modified"):
        package_reviewers(study, plan, tmp_path / "no-package")
    assert not (tmp_path / "no-package").exists()


def test_cli_preflight_status_no_overwrites(tmp_path: Path, capsys):
    study, plan, _ = _scenario(tmp_path)
    report = tmp_path / "preflight.json"
    assert main(["preflight", "--study-dir", str(study), "--plan", str(plan),
                 "--output", str(report)]) == 0
    assert report.is_file()
    assert main(["preflight", "--study-dir", str(study),
                 "--output", str(report)]) == 2
    assert "Study operations error" in capsys.readouterr().err
    a, b = study / "reviewer_a.json", study / "reviewer_b.json"
    assert main(["status", "--study-dir", str(study),
                 "--reviewer-a", str(a), "--reviewer-b", str(b)]) == 0
    assert '"review_incomplete"' in capsys.readouterr().out


def test_summarize_requires_valid_evaluated_report(tmp_path: Path):
    study, plan, _ = _scenario(tmp_path)
    with pytest.raises(PilotError, match="query-level"):
        summarize_analysis({"foo": "bar"})
    workbook = json.loads((study / "review_template.json").read_text())
    first_item = workbook["judgments"][0]["item_id"]
    for row in workbook["judgments"]:
        positive = row["case_id"].endswith("1") and row["item_id"] == first_item
        row["reviews"] = {"reviewer_a": positive, "reviewer_b": positive}
        row["reviewer_notes"] = {
            "reviewer_a": "Fictional evidence" if positive else "",
            "reviewer_b": "Fictional evidence" if positive else "",
        }
        row["final_label"] = positive
    book_path = _write(tmp_path / "fictional-workbook.json", workbook)
    result = analyze_reviewed_study(study, book_path, plan)
    markdown = summarize_analysis(result)
    assert "BM25 − overlap" in markdown
    assert "This partition contains 2 queries" in markdown
    assert "ndcg_at_k" in markdown
    assert "fictional" not in markdown.casefold()  # A generic template, not evidence
    raw_path = _write(tmp_path / "analysis.json", result)
    output_path = tmp_path / "summary.md"
    assert main(["summarize", "--analysis", str(raw_path),
                 "--output", str(output_path)]) == 0
    assert output_path.read_text() == markdown
    assert main(["summarize", "--analysis", str(raw_path),
                 "--output", str(output_path)]) == 2


def test_exclusive_output_rejects_existing_file_and_symlink(tmp_path: Path):
    file = tmp_path / "existing.json"
    _write_new(file, b"first")
    with pytest.raises(FileExistsError):
        _write_new(file, b"second")
    assert file.read_bytes() == b"first"
    symlink = tmp_path / "linked.json"
    symlink.symlink_to(file)
    with pytest.raises(FileExistsError):
        _write_new(symlink, b"second")
    assert file.read_bytes() == b"first"
