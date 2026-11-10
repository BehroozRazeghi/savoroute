"""Reference annotations, missing-source behavior, and field-level metrics."""

import json
from pathlib import Path

import pytest

from savoroute.cli import main
from savoroute.data.catalog import load_catalog
from savoroute.evaluation.extraction import AnnotationError, evaluate_extraction
from savoroute.ingestion.extraction import LabeledTextExtractor
from savoroute.ingestion.sources import parse_source_batch
from savoroute.services.ingestion import ingest_sources

DATA = Path(__file__).resolve().parents[1] / "data/sample"


@pytest.fixture
def inputs():
    source = json.loads((DATA / "ingestion_sources.json").read_text())
    gold = json.loads((DATA / "extraction_gold.json").read_text())
    report = ingest_sources(parse_source_batch(source), LabeledTextExtractor(),
                            base_catalog=load_catalog()).provenance()
    return gold, report


def test_perfect_fixture(inputs):
    gold, report = inputs
    summary = evaluate_extraction(gold, report)
    assert summary.gold_records == 2
    assert summary.exact_records == 2
    assert summary.micro.f1 == 1.0
    assert summary.fields["ingredients"].recall == 1.0
    assert summary.fields["location"].recall == 1.0
    assert summary.fields["price_tier"].precision == 1.0


def test_wrong_field_counts_as_fp_and_fn(inputs):
    gold, report = inputs
    report["records"][0]["evidence"]["cuisines"][0]["value"] = "fusion"
    result = evaluate_extraction(gold, report)
    assert result.fields["cuisines"].false_positive == 1
    assert result.fields["cuisines"].false_negative == 1
    assert result.exact_records == 1
    assert result.errors[gold["records"][0]["source_id"]] == ["cuisines"]


def test_missing_prediction_is_false_negative(inputs):
    gold, report = inputs
    report["records"] = report["records"][:1]
    result = evaluate_extraction(gold, report)
    assert result.predicted_records == 1
    assert result.exact_records == 1
    assert result.fields["title"].false_negative == 1


def test_unknown_prediction_rejected(inputs):
    gold, report = inputs
    report["records"][0]["source_id"] = "unexpected"
    with pytest.raises(AnnotationError, match="absent from gold"):
        evaluate_extraction(gold, report)


def test_dataset_mismatch(inputs):
    gold, report = inputs
    gold["dataset"] = "another dataset"
    with pytest.raises(AnnotationError, match="does not match"):
        evaluate_extraction(gold, report)


def test_duplicate_gold_id_rejected(inputs):
    gold, report = inputs
    gold["records"].append(gold["records"][0])
    with pytest.raises(AnnotationError, match="unique"):
        evaluate_extraction(gold, report)


def test_casefold_whitespace_normalization(inputs):
    gold, report = inputs
    gold["records"][0]["fields"]["title"] = "  GINGER   MUSHROOM rice "
    assert evaluate_extraction(gold, report).exact_records == 2


def test_invalid_list_and_wrong_types(inputs):
    gold, report = inputs
    gold["records"][0]["fields"]["ingredients"] = [None]
    with pytest.raises(AnnotationError, match="ingredients"):
        evaluate_extraction(gold, report)
    gold["records"][0]["fields"]["ingredients"] = []
    report["records"][0]["evidence"]["price_tier"] = [
        {"value": True, "quote": "irrelevant", "start": 0, "end": 10}
    ]
    with pytest.raises(AnnotationError, match="price_tier"):
        evaluate_extraction(gold, report)


def test_cli_eval(tmp_path, inputs, capsys):
    gold, report = inputs
    gold_path, predictions_path = tmp_path / "gold.json", tmp_path / "predictions.json"
    gold_path.write_text(json.dumps(gold))
    predictions_path.write_text(json.dumps(report))
    assert main(["evaluate-extraction", "--gold", str(gold_path),
                 "--predictions", str(predictions_path), "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["record_exact_match_rate"] == 1.0
    assert summary["micro"]["f1"] == 1.0
