"""Tests for identity-candidate evaluation and annotation worksheet creation."""

import copy
import json
from pathlib import Path

import pytest

from savoroute.cli import main
from savoroute.evaluation.identity import (
    evaluate_identity_candidates,
    load_identity_benchmark,
    parse_identity_benchmark,
)
from savoroute.identity.annotations import prepare_osm_annotations
from savoroute.ingestion.sources import IngestionError

BENCHMARK = Path("data/sample/identity_pairs_fixture.json")
SNAPSHOT = Path("data/sample/osm_overpass_fixture.json")


def test_fixture_measurements_include_both_error_types():
    summary = evaluate_identity_candidates(load_identity_benchmark(BENCHMARK))
    assert (summary.pairs, summary.true_positive, summary.false_positive,
            summary.false_negative, summary.true_negative) == (14, 1, 3, 1, 9)
    assert summary.precision == 0.25
    assert summary.recall == 0.5
    assert summary.review_rate == 4 / 14
    assert summary.false_negative_pairs == (("r4", "r5"),)
    assert summary.false_positive_pairs == (("r1", "r3"), ("r2", "r3"), ("r7", "r8"))


def test_cli_evaluate_has_json_and_text(capsys):
    assert main(["identity", "evaluate", "--benchmark", str(BENCHMARK), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["fn"] == 1
    assert main(["identity", "evaluate", "--benchmark", str(BENCHMARK)]) == 0
    assert "Precision=0.250" in capsys.readouterr().out


def test_cli_preparation_is_unlabeled_and_cannot_be_scored(tmp_path, capsys):
    out = tmp_path / "review.json"
    assert main(["identity", "prepare-osm", "--input", str(SNAPSHOT),
                 "--output", str(out)]) == 0
    worksheet = json.loads(out.read_text())
    assert worksheet["dataset"]["synthetic"] is True
    assert worksheet["pairs"]
    assert all(pair["same_entity"] is None for pair in worksheet["pairs"])
    assert main(["identity", "evaluate", "--benchmark", str(out)]) == 2
    assert "explicit boolean" in capsys.readouterr().err
    # Existing CLI output is never overwritten without an explicit update.
    assert main(["identity", "prepare-osm", "--input", str(SNAPSHOT),
                 "--output", str(out)]) == 2
    assert "already exists" in capsys.readouterr().err


@pytest.mark.parametrize("change", [
    lambda b: b["pairs"][0].update({"same_entity": None}),
    lambda b: b["pairs"].append(dict(b["pairs"][0],
                                     left_id=b["pairs"][0]["right_id"],
                                     right_id=b["pairs"][0]["left_id"])),
    lambda b: b["pairs"][0].update({"left_id": "missing"}),
    lambda b: b["pairs"][0].update({"right_id": b["pairs"][0]["left_id"]}),
    lambda b: b["records"][0].update({"latitude": float("nan")}),
    lambda b: b["records"][0].update({"longitude": None}),
    lambda b: b["records"].append(copy.deepcopy(b["records"][0])),
    lambda b: b.update({"unexpected": 1}),
    lambda b: b["dataset"].update({"synthetic": 1}),
])
def test_reject_malformed_benchmark(change):
    original = json.loads(BENCHMARK.read_text())
    change(original)
    with pytest.raises(IngestionError):
        parse_identity_benchmark(original)


def test_unlabeled_prep_is_bounded_and_handles_duplicates():
    payload = json.loads(SNAPSHOT.read_text())
    worksheet = prepare_osm_annotations(payload, max_records=3, max_pairs=2)
    assert len(worksheet["records"]) == 3
    assert len(worksheet["pairs"]) == 2
    with pytest.raises(IngestionError, match="max_records"):
        prepare_osm_annotations(payload, max_records=101)
    with pytest.raises(IngestionError, match="max_pairs"):
        prepare_osm_annotations(payload, max_pairs=0)
    payload["elements"].append(copy.deepcopy(payload["elements"][0]))
    with pytest.raises(IngestionError, match="duplicate"):
        prepare_osm_annotations(payload)


def test_zero_predicted_candidates_metrics():
    raw = json.loads(BENCHMARK.read_text())
    raw["pairs"] = [{"left_id": "r1", "right_id": "r6", "same_entity": False}]
    result = evaluate_identity_candidates(parse_identity_benchmark(raw))
    assert result.precision is None and result.recall is None and result.f1 is None
    assert result.review_rate == 0.0
