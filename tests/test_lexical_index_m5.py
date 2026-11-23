"""Independent parity oracle and catalog-bound cache integration tests."""

from __future__ import annotations

import math
import random
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from savoroute.data.catalog import load_catalog
from savoroute.domain.models import CatalogItem
from savoroute.retrieval.lexical import (
    LexicalIndex,
    SearchFilters,
    filter_catalog,
    search_catalog,
    tokenize,
)
from savoroute.services.discovery import DiscoveryService


def _reference_search(items, query, filters=None, *, method="bm25", limit=5):
    """Reference formula copied into the test (not delegated to LexicalIndex)."""
    records = tuple(items)
    terms = tuple(dict.fromkeys(tokenize(query)))
    selected = filter_catalog(records, filters)
    if not terms or not selected:
        return ()
    documents = {}
    for item in records:
        parts = [item.title] * 3 + [" ".join(item.cuisines)] * 2
        parts.extend((item.description, " ".join(item.dietary_tags),
                      " ".join(item.ingredients)))
        if item.location:
            parts.append(item.location)
        documents[item.item_id] = Counter(tokenize(" ".join(parts)))
    lengths = {key: sum(doc.values()) for key, doc in documents.items()}
    average_length = sum(lengths.values()) / len(lengths)
    df = {term: sum(doc[term] > 0 for doc in documents.values()) for term in terms}
    query_set = set(terms)
    output = []
    for item in selected:
        if method == "bm25":
            score = 0.0
            for term in terms:
                tf = documents[item.item_id][term]
                if not tf:
                    continue
                idf = math.log(1 + (len(records) - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * (tf * (1.5 + 1)) / (
                    tf + 1.5 * (1 - 0.75 + 0.75 * lengths[item.item_id] / average_length)
                )
        else:
            fields = (
                item.title, " ".join(item.cuisines), " ".join(item.dietary_tags),
                item.description, item.location or "", " ".join(item.ingredients),
            )
            score = float(sum(
                weight * len(query_set.intersection(tokenize(value)))
                for weight, value in zip((5, 3, 2, 1, 1, 1), fields, strict=True)
            ))
        if score > 0:
            output.append((item.item_id, score,
                           tuple(sorted(query_set.intersection(documents[item.item_id])))))
    output.sort(key=lambda result: (-result[1], result[0]))
    return tuple(output[:limit])


def _flatten(hits):
    return tuple((hit.item.item_id, hit.score, hit.matched_terms) for hit in hits)


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.mark.parametrize("method", ["bm25", "overlap"])
@pytest.mark.parametrize("query", [
    "spicy tofu noodles", "TOFU tofu pasta", "café noodles", "Boston", "", " no-such-term ",
    "Mediterranean hummus vegan", "price restaurant", "hummus! recipe??", "x y z",
])
@pytest.mark.parametrize("filters", [
    None, SearchFilters(kind="recipe"), SearchFilters(kind="restaurant"),
    SearchFilters(cuisine="Mediterranean"), SearchFilters(location="Sample City"),
    SearchFilters(max_price_tier=1), SearchFilters(dietary_tags=("vegan-options",)),
    SearchFilters(city="Boston"),
])
def test_scores_ids_and_explanations_exact(catalog, query, filters, method):
    index = LexicalIndex.build(catalog.items)
    expected = _reference_search(catalog.items, query, filters, method=method, limit=50)
    actual = index.search(query, filters, method=method, limit=50)
    assert _flatten(actual) == expected
    assert search_catalog(catalog.items, query, filters, method=method, limit=50,
                          lexical_index=index) == actual


def test_deterministic_random_queries_and_ties(catalog):
    records = catalog.items
    tokens = sorted({term for item in records for term in tokenize(item.title + " " + item.description)})
    randomizer = random.Random(20261113)
    index = LexicalIndex.build(records)
    for _ in range(100):
        query = " ".join(randomizer.choices(tokens, k=randomizer.randint(1, 6)))
        for method in ("bm25", "overlap"):
            assert _flatten(index.search(query, limit=20, method=method)) == _reference_search(
                records, query, limit=20, method=method
            )


def test_index_is_catalog_bound_and_read_only(catalog):
    index = LexicalIndex.build(catalog.items)
    assert isinstance(index._document_frequency, MappingProxyType)
    with pytest.raises(TypeError):
        index._document_frequency["tofu"] = 99
    altered = (replace(catalog.items[0], title="new version"), *catalog.items[1:])
    with pytest.raises(ValueError, match="different catalog"):
        search_catalog(altered, "tofu", lexical_index=index)
    with pytest.raises(ValueError, match="different catalog"):
        search_catalog(iter(catalog.items), "tofu", lexical_index=index)
    assert LexicalIndex.build(altered).items[0].title == "new version"


def test_service_all_paths_reuse_catalog_index(catalog):
    service = DiscoveryService(catalog)
    index = service.lexical_index
    assert service.search("noodles") == index.search("noodles")
    assert service.rank("noodles")
    assert service.recommend("noodles").results
    assert service.lexical_index is index


def test_empty_catalog_and_duplicates(catalog):
    assert LexicalIndex.build(()).search("x") == ()
    with pytest.raises(ValueError, match="duplicate catalog item_id"):
        LexicalIndex.build((catalog.items[0], catalog.items[0]))


def test_full_catalog_idf_is_not_filter_dependent(catalog):
    index = LexicalIndex.build(catalog.items)
    unrestricted = {hit.item.item_id: hit.score for hit in index.search("hummus", limit=100)}
    restricted = index.search("hummus", SearchFilters(kind="restaurant"), limit=100)
    assert restricted
    assert all(hit.score == unrestricted[hit.item.item_id] for hit in restricted)


def test_score_is_not_modified_by_unrelated_metadata(catalog):
    index = LexicalIndex.build(catalog.items)
    altered = (replace(catalog.items[0], latitude=40.0, longitude=-71.0), *catalog.items[1:])
    newer = LexicalIndex.build(altered)
    assert _flatten(index.search("tofu noodle")) == _flatten(newer.search("tofu noodle"))


def test_missing_document_tokens_do_not_divide_by_zero():
    blank = CatalogItem("empty", "recipe", "", "", (), (), "unit-test")
    index = LexicalIndex.build((blank,))
    assert index.search("anything") == ()


def test_latency_benchmark_is_reproducible_in_shape_and_non_overwriting(tmp_path):
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_lexical.py"
    spec = importlib.util.spec_from_file_location("bench_lexical", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.run_benchmark(None, repeat=2, loops=1, warmup=0)
    assert report["replication_factor"] == 2
    assert report["query_count"] == 6
    for method in ("bm25", "overlap"):
        assert report["methods"][method]["stateless"]["count"] == 6
        assert report["methods"][method]["indexed"]["count"] == 6
    output = tmp_path / "test-report.json"
    assert module.main(["--loops", "1", "--warmup", "0", "--output", str(output)]) == 0
    assert module.main(["--loops", "1", "--warmup", "0", "--output", str(output)]) == 2
    assert "local_lexical_latency_microbenchmark_v1" in output.read_text()
