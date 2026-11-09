"""Same public functionality must work from the console entry point."""

import json

from savoroute.cli import main


def test_demo(capsys):
    assert main(["demo"]) == 0
    assert "Demo catalog: fictional records (offline)." in capsys.readouterr().out


def test_validate(capsys):
    assert main(["validate"]) == 0
    assert "items=12" in capsys.readouterr().out


def test_search_json(capsys):
    assert main(["search", "spicy tofu noodles", "--kind", "recipe", "--json"]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert hits[0]["item_id"] == "p001"
    assert hits[0]["method"] == "bm25"


def test_search_overlap(capsys):
    assert main(["search", "spicy tofu noodles", "--method", "overlap", "--json"]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert hits[0]["method"] == "overlap"


def test_evaluate_json(capsys):
    assert main(["evaluate", "--method", "both", "--json"]) == 0
    summaries = json.loads(capsys.readouterr().out)
    assert {s["method"] for s in summaries} == {"bm25", "overlap"}


def test_missing_catalog_error(capsys):
    assert main(["validate", "--catalog", "missing-not-here.json"]) == 2
    assert "Error:" in capsys.readouterr().err


def test_invalid_limit_error(capsys):
    assert main(["search", "noodle", "--limit", "0"]) == 2
    assert "limit" in capsys.readouterr().err


def test_valid_no_match_json(capsys):
    assert main(["search", "nebula quasar", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
