"""Grounded retrieval, filters and scoring-convention tests."""

from dataclasses import replace

import pytest

from savoroute.data.catalog import load_catalog
from savoroute.retrieval.lexical import SearchFilters, filter_catalog, search_catalog, tokenize
from savoroute.services.discovery import DiscoveryService


@pytest.fixture(scope="module")
def records():
    return load_catalog().items


@pytest.mark.parametrize("method", ["bm25", "overlap"])
def test_recipe_search_is_grounded(records, method):
    hits = search_catalog(records, "spicy tofu noodles", SearchFilters(kind="recipe"),
                          method=method)
    assert hits[0].item.item_id == "p001"
    assert all(hit.item in records and hit.score > 0 for hit in hits)
    assert all(hit.method == method for hit in hits)


def test_distinct_baseline_scores(records):
    a = search_catalog(records, "tofu noodle", method="overlap")
    b = search_catalog(records, "tofu noodle", method="bm25")
    assert a and b
    assert a[0].score != b[0].score


def test_hard_filters(records):
    filters = SearchFilters(kind="restaurant", cuisine="Mediterranean",
                            location="Sample City", max_price_tier=2,
                            dietary_tags=("vegan-options",))
    hits = search_catalog(records, "hummus vegetables", filters)
    assert len(hits) == 1
    assert hits[0].item.item_id == "r002"


def test_recipe_vegan_tag_does_not_imply_restaurant_vegan(records):
    # A restaurant's 'vegan-options' is intentionally different from 'vegan'.
    hits = search_catalog(records, "vegan", SearchFilters(
        kind="restaurant", dietary_tags=("vegan",)
    ))
    assert not hits


def test_filter_unknown_metadata_fails_closed(records):
    selected = filter_catalog(records, SearchFilters(max_price_tier=1))
    assert all(item.price_tier is not None and item.price_tier <= 1 for item in selected)
    assert all(item.kind == "restaurant" for item in selected)


def test_bm25_stats_stable_across_filter(records):
    unrestricted = search_catalog(records, "pasta", method="bm25")
    restricted = search_catalog(records, "pasta", SearchFilters(kind="recipe"), method="bm25")
    scores = {hit.item.item_id: hit.score for hit in unrestricted}
    assert restricted
    for hit in restricted:
        assert hit.score == scores[hit.item.item_id]


def test_empty_returns_no_matches(records):
    assert search_catalog(records, " ") == ()
    assert search_catalog(records, "quasar xylophone nebula") == ()


def test_no_unsupported_candidates(records):
    ids = {item.item_id for item in records}
    for method in ("overlap", "bm25"):
        hits = search_catalog(records, "noodles", method=method)
        assert {hit.item.item_id for hit in hits}.issubset(ids)


@pytest.mark.parametrize("limit", [0, -1, True])
def test_bad_limit(records, limit):
    with pytest.raises(ValueError):
        search_catalog(records, "noodle", limit=limit)


@pytest.mark.parametrize("method", ["dense", "vector", "llm"])
def test_unimplemented_methods_rejected(records, method):
    with pytest.raises(ValueError):
        search_catalog(records, "noodle", method=method)


def test_duplicate_catalog_items_rejected(records):
    with pytest.raises(ValueError, match="duplicate"):
        search_catalog((*records, records[0]), "noodle")


def test_tokenizer_english_baseline():
    assert tokenize("Italian, Italian? TOFU!") == ("italian", "italian", "tofu")


def test_service_delegates_to_retrieval(records):
    service = DiscoveryService(load_catalog())
    assert service.search("tofu noodle") == search_catalog(records, "tofu noodle")


def test_metadata_changes_do_not_change_existing_record_id(records):
    altered = replace(records[0], description="A revised but still fictional description")
    assert altered.item_id == records[0].item_id


def test_filter_validation_rejects_string_not_tuple():
    with pytest.raises(ValueError, match="dietary_tags"):
        SearchFilters(dietary_tags="vegan")


def test_filter_validation_rejects_nonstr_kind():
    with pytest.raises(ValueError, match="kind"):
        SearchFilters(kind=12)


def test_filters_strip_surrounding_whitespace(records):
    with_whitespace = SearchFilters(kind="restaurant", cuisine=" Mediterranean ",
                                     location=" Sample City ",
                                     dietary_tags=(" vegan-options ",))
    hits = search_catalog(records, "hummus", with_whitespace)
    assert [hit.item.item_id for hit in hits] == ["r002"]
