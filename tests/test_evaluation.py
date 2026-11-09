"""Benchmark schema validation and metric edge cases."""

import json
from importlib.resources import files

import pytest

from savoroute.data.catalog import load_catalog
from savoroute.evaluation.retrieval import (
    BenchmarkError,
    QueryJudgment,
    evaluate_search,
    load_benchmark,
    parse_benchmark,
)
from savoroute.retrieval.lexical import SearchFilters


def payload():
    return json.loads(files("savoroute.resources").joinpath("demo_benchmark.json").read_text())


def test_benchmark_bundled_and_sample_match():
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    assert load_benchmark() == load_benchmark(repo / "data/sample/relevance_benchmark.json")
    assert len(load_benchmark()) == 16


@pytest.mark.parametrize("method", ["bm25", "overlap"])
def test_evaluation_metrics_finite(method):
    summary = evaluate_search(load_catalog().items, load_benchmark(), method=method, at_k=3)
    assert summary.positive_queries == 14
    assert summary.empty_queries == 2
    assert 0 <= summary.mean_recall_at_k <= 1
    assert 0 <= summary.mrr_at_k <= 1
    assert 0 <= summary.mean_ndcg_at_k <= 1
    assert 0 <= summary.correct_empty_rate <= 1
    assert summary.as_dict()["method"] == method


def test_no_match_only_has_defined_rate():
    j = QueryJudgment("empty", "quasar nebula", frozenset(), SearchFilters())
    summary = evaluate_search(load_catalog().items, [j])
    assert summary.mean_recall_at_k is None
    assert summary.mrr_at_k is None
    assert summary.mean_ndcg_at_k is None
    assert summary.correct_empty_rate == 1.0


def test_unknown_relevant_id_fails():
    j = QueryJudgment("bad", "noodles", frozenset({"not-in-catalog"}), SearchFilters())
    with pytest.raises(BenchmarkError, match="unknown relevant"):
        evaluate_search(load_catalog().items, [j])


def test_relevant_item_excluded_by_filters_fails():
    j = QueryJudgment("bad", "noodle", frozenset({"p001"}),
                      SearchFilters(kind="restaurant"))
    with pytest.raises(BenchmarkError, match="violate filters"):
        evaluate_search(load_catalog().items, [j])


def test_duplicate_case_ids_fails():
    j = QueryJudgment("same", "noodle", frozenset(), SearchFilters())
    with pytest.raises(BenchmarkError, match="duplicate"):
        evaluate_search(load_catalog().items, [j, j])


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(benchmark_version=True),
    lambda p: p.update(unknown="extra"),
    lambda p: p["queries"][0].update(relevant_item_ids=["p001", "p001"]),
    lambda p: p["queries"][0].update(filters={"max_price_tier": True}),
    lambda p: p["queries"][0].update(filters={"bad": "value"}),
    lambda p: p["queries"][0].update(case_id=""),
])
def test_invalid_benchmark_rejected(mutation):
    p = payload()
    mutation(p)
    with pytest.raises(BenchmarkError):
        parse_benchmark(p)


@pytest.mark.parametrize("k", [0, -3, True])
def test_invalid_k_rejected(k):
    with pytest.raises(ValueError):
        evaluate_search(load_catalog().items, load_benchmark(), at_k=k)
