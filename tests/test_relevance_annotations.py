"""Versioned review worksheets and strict relevance judgment finalization."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from savoroute.data.catalog import load_catalog
from savoroute.evaluation.annotations import (
    RelevanceAnnotationError,
    finalize_relevance_workbook,
    prepare_relevance_workbook,
)
from savoroute.evaluation.retrieval import evaluate_search, parse_benchmark

CATALOG = load_catalog()
QUERIES = {
    "query_set_version": 1,
    "queries": [
        {"case_id": "dev-1", "query": "spicy tofu", "split": "development",
         "filters": {"kind": "recipe"}},
        {"case_id": "test-1", "query": "nonexistent purple dish", "split": "test",
         "filters": {"kind": "recipe"}},
    ],
}


def reviewed_workbook():
    result = prepare_relevance_workbook(CATALOG, QUERIES)
    for row in result["judgments"]:
        true_label = row["case_id"] == "dev-1" and row["item_id"] == "p001"
        row["reviews"] = {"reviewer_a": true_label, "reviewer_b": true_label}
        row["final_label"] = true_label
        if true_label:
            row["reviewer_notes"] = {
                "reviewer_a": "Synthetic match to supplied demo item",
                "reviewer_b": "Synthetic match to supplied demo item",
            }
    return result


def test_workbook_exhaustive_and_stable():
    workbook = prepare_relevance_workbook(CATALOG, QUERIES)
    assert workbook == prepare_relevance_workbook(CATALOG, QUERIES)
    assert workbook["synthetic"] is True
    assert len(workbook["judgments"]) == 12
    assert all(row["reviews"]["reviewer_a"] is None for row in workbook["judgments"])
    assert all(row["item_id"].startswith("p") for row in workbook["judgments"])
    with pytest.raises(RelevanceAnnotationError, match="max_pairs"):
        prepare_relevance_workbook(CATALOG, QUERIES, max_pairs=2)


def test_finalization_produces_compatible_benchmarks_and_audit():
    dev, test, audit = finalize_relevance_workbook(CATALOG, reviewed_workbook())
    assert parse_benchmark(dev)[0].relevant_item_ids == frozenset({"p001"})
    assert not parse_benchmark(test)[0].relevant_item_ids
    assert audit["judged_pairs"] == 12
    assert audit["disagreements"] == 0
    assert audit["observed_agreement"] == 1
    assert audit["synthetic"] is True
    summary = evaluate_search(CATALOG.items, parse_benchmark(dev), at_k=5)
    assert summary.positive_queries == 1


def test_incomplete_review_and_disagreements_block_export():
    blank = prepare_relevance_workbook(CATALOG, QUERIES)
    with pytest.raises(RelevanceAnnotationError, match="unfinished reviews"):
        finalize_relevance_workbook(CATALOG, blank)
    conflicting = reviewed_workbook()
    conflicting["judgments"][0]["reviews"]["reviewer_b"] = not conflicting["judgments"][0]["reviews"]["reviewer_a"]
    with pytest.raises(RelevanceAnnotationError, match="disagreement needs"):
        finalize_relevance_workbook(CATALOG, conflicting)
    if conflicting["judgments"][0]["reviews"]["reviewer_b"]:
        conflicting["judgments"][0]["reviewer_notes"]["reviewer_b"] = "Synthetic label"
    conflicting["judgments"][0]["adjudication_note"] = "Synthetic adjudication example"
    _, _, audit = finalize_relevance_workbook(CATALOG, conflicting)
    assert audit["disagreements"] == 1
    assert audit["cohen_kappa"] is not None


def test_agreement_cannot_be_overridden_and_bool_labels_are_required():
    corrupted = reviewed_workbook()
    corrupted["judgments"][0]["final_label"] = not corrupted["judgments"][0]["final_label"]
    with pytest.raises(RelevanceAnnotationError, match="agreement contradicted"):
        finalize_relevance_workbook(CATALOG, corrupted)
    corrupted = reviewed_workbook()
    corrupted["judgments"][0]["reviews"]["reviewer_a"] = 1
    with pytest.raises(RelevanceAnnotationError, match="unfinished reviews"):
        finalize_relevance_workbook(CATALOG, corrupted)


@pytest.mark.parametrize("change", [
    lambda w: w.update({"catalog_sha256": "0" * 64}),
    lambda w: w["judgments"].pop(),
    lambda w: w["judgments"].append(copy.deepcopy(w["judgments"][0])),
    lambda w: w["judgments"][0].update({"item_id": "unknown"}),
    lambda w: w["queries"][0]["filters"].update({"cuisine": "Japanese"}),
    lambda w: w["queries"][0].update({"case_id": "test-1"}),
])
def test_untrusted_or_stale_workbooks_are_rejected(change):
    w = reviewed_workbook()
    change(w)
    with pytest.raises(RelevanceAnnotationError):
        finalize_relevance_workbook(CATALOG, w)


def test_invalid_query_set_and_split():
    wrong = copy.deepcopy(QUERIES)
    wrong["queries"][0]["split"] = "test"
    with pytest.raises(RelevanceAnnotationError, match="development and test"):
        prepare_relevance_workbook(CATALOG, wrong)
    wrong = copy.deepcopy(QUERIES)
    wrong["queries"][0]["filters"]["dietary_tags"] = "vegan"
    with pytest.raises(RelevanceAnnotationError, match="dietary_tags"):
        prepare_relevance_workbook(CATALOG, wrong)


def test_cli_prepare_and_incomplete_finalize(tmp_path: Path, capsys):
    from savoroute.cli import main

    query_file = tmp_path / "queries.json"
    query_file.write_text(json.dumps(QUERIES), encoding="utf-8")
    workbook_file = tmp_path / "worksheet.json"
    catalog_path = Path(__file__).resolve().parents[1] / "data/sample/catalog.json"
    assert main(["judgments", "prepare", "--catalog", str(catalog_path),
                 "--queries", str(query_file), "--output", str(workbook_file)]) == 0
    assert workbook_file.exists()
    assert main(["judgments", "finalize", "--catalog", str(catalog_path),
                 "--workbook", str(workbook_file),
                 "--output-dir", str(tmp_path / "out")]) == 2
    assert "unfinished" in capsys.readouterr().err
    reviewed = reviewed_workbook()
    workbook_file.write_text(json.dumps(reviewed), encoding="utf-8")
    assert main(["judgments", "finalize", "--catalog", str(catalog_path),
                 "--workbook", str(workbook_file),
                 "--output-dir", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "development.json").exists()
    assert (tmp_path / "out" / "test.json").exists()
    assert (tmp_path / "out" / "audit.json").exists()
    assert main(["judgments", "finalize", "--catalog", str(catalog_path),
                 "--workbook", str(workbook_file),
                 "--output-dir", str(tmp_path / "out")]) == 2


def test_positive_review_requires_rationale():
    workbook = reviewed_workbook()
    positive = next(row for row in workbook["judgments"] if row["final_label"])
    positive["reviewer_notes"]["reviewer_a"] = ""
    with pytest.raises(RelevanceAnnotationError, match="positive judgments require"):
        finalize_relevance_workbook(CATALOG, workbook)


def test_worksheet_copies_query_set_instead_of_mutating_it():
    original = copy.deepcopy(QUERIES)
    workbook = prepare_relevance_workbook(CATALOG, QUERIES)
    workbook["queries"][0]["query"] = "changed only in workbook"
    assert QUERIES == original


def test_catalog_reordering_invalidates_workbook():
    from dataclasses import replace

    workbook = reviewed_workbook()
    reordered = replace(CATALOG, items=tuple(reversed(CATALOG.items)))
    with pytest.raises(RelevanceAnnotationError, match="incompatible"):
        finalize_relevance_workbook(reordered, workbook)


def test_blind_reviewer_files_merge_and_adjudication():
    from savoroute.evaluation.annotations import (
        merge_reviewer_sheets,
        split_reviewer_sheets,
    )

    template = prepare_relevance_workbook(CATALOG, QUERIES)
    reviewer_a, reviewer_b = split_reviewer_sheets(CATALOG, template)
    assert "reviewer_b" not in json.dumps(reviewer_a)
    assert "reviewer_a" not in json.dumps(reviewer_b)
    assert reviewer_a["template_sha256"] == reviewer_b["template_sha256"]
    for r in (reviewer_a, reviewer_b):
        for row in r["judgments"]:
            label = row["case_id"] == "dev-1" and row["item_id"] == "p001"
            row["relevant"] = label
            row["note"] = "Synthetic review, not a human annotation" if label else ""
    reviewer_b["judgments"][0]["relevant"] = not reviewer_b["judgments"][0]["relevant"]
    reviewer_b["judgments"][0]["note"] = "Synthetic disagreement"
    merged = merge_reviewer_sheets(CATALOG, template, reviewer_a, reviewer_b)
    assert merged["judgments"][0]["final_label"] is None
    with pytest.raises(RelevanceAnnotationError, match="unfinished adjudication"):
        finalize_relevance_workbook(CATALOG, merged)
    merged["judgments"][0]["final_label"] = merged["judgments"][0]["reviews"]["reviewer_a"]
    merged["judgments"][0]["adjudication_note"] = "Synthetic adjudicator decision"
    dev, test, audit = finalize_relevance_workbook(CATALOG, merged)
    assert audit["disagreements"] == 1
    assert dev["benchmark_version"] == test["benchmark_version"] == 1


def test_reviewer_sheet_integrity_and_completeness():
    from savoroute.evaluation.annotations import (
        merge_reviewer_sheets,
        split_reviewer_sheets,
    )

    template = prepare_relevance_workbook(CATALOG, QUERIES)
    first, second = split_reviewer_sheets(CATALOG, template)
    with pytest.raises(RelevanceAnnotationError, match="reviewer judgment is incomplete"):
        merge_reviewer_sheets(CATALOG, template, first, second)
    with pytest.raises(RelevanceAnnotationError, match="metadata mismatch"):
        merge_reviewer_sheets(CATALOG, template, second, first)
    first["judgments"].pop()
    with pytest.raises(RelevanceAnnotationError, match="coverage"):
        merge_reviewer_sheets(CATALOG, template, first, second)


def test_cli_split_and_merge_review_sheets(tmp_path: Path, capsys):
    from savoroute.cli import main

    catalog_path = Path(__file__).resolve().parents[1] / "data/sample/catalog.json"
    query_file = tmp_path / "queries.json"
    query_file.write_text(json.dumps(QUERIES), encoding="utf-8")
    template_file = tmp_path / "template.json"
    assert main(["judgments", "prepare", "--catalog", str(catalog_path),
                 "--queries", str(query_file), "--output", str(template_file)]) == 0
    output_dir = tmp_path / "reviewers"
    assert main(["judgments", "split", "--catalog", str(catalog_path),
                 "--workbook", str(template_file), "--output-dir", str(output_dir)]) == 0
    a_file, b_file = output_dir / "reviewer_a.json", output_dir / "reviewer_b.json"
    for file in (a_file, b_file):
        payload = json.loads(file.read_text(encoding="utf-8"))
        for row in payload["judgments"]:
            label = row["case_id"] == "dev-1" and row["item_id"] == "p001"
            row["relevant"] = label
            row["note"] = "Synthetic sample answer" if label else ""
        file.write_text(json.dumps(payload), encoding="utf-8")
    merged_file = tmp_path / "merged.json"
    assert main(["judgments", "merge", "--catalog", str(catalog_path),
                 "--workbook", str(template_file), "--reviewer-a", str(a_file),
                 "--reviewer-b", str(b_file), "--output", str(merged_file)]) == 0
    assert main(["judgments", "finalize", "--catalog", str(catalog_path),
                 "--workbook", str(merged_file),
                 "--output-dir", str(tmp_path / "qrels")]) == 0
    assert (tmp_path / "qrels" / "audit.json").exists()
