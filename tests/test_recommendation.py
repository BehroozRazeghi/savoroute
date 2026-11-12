"""Evidence-backed, deterministic recommendation policy."""

from __future__ import annotations

import json

import pytest

from savoroute.data.catalog import load_catalog
from savoroute.retrieval.lexical import SearchFilters
from savoroute.services.discovery import DiscoveryService
from savoroute.services.recommendation import RecommendationPreferences, recommend_items

CATALOG = load_catalog()


def test_provenance_and_ranking_evidence_are_catalog_grounded():
    response = recommend_items(CATALOG, "spicy tofu noodles", filters=SearchFilters(kind="recipe"))
    assert response.synthetic and response.status == "ok"
    assert response.results
    for row in response.results:
        canonical = CATALOG.get(row.item.item_id)
        data = row.as_dict()
        assert canonical is not None
        assert data["title"] == canonical.title
        assert data["source"] == canonical.source
        assert data["source_url"] == canonical.source_url
        assert data["retrieval_evidence"]
        assert all(e["source"] in ("bm25", "text", "image") for e in data["retrieval_evidence"])
    assert response.results[0].item.item_id == "p001"


def test_hard_constraints_fail_closed_not_synonymized():
    # Restaurant 'vegan-options' does not satisfy the different tag 'vegan'.
    response = recommend_items(CATALOG, "Mediterranean", filters=SearchFilters(
        kind="restaurant", dietary_tags=("vegan",),
    ))
    assert response.status == "no_eligible_items" and not response.results
    response = recommend_items(CATALOG, "Mediterranean", filters=SearchFilters(
        kind="restaurant", location="Sample City", max_price_tier=2,
        dietary_tags=("vegan-options",),
    ))
    assert all(row.item.item_id == "r002" for row in response.results)
    assert response.eligible_items == 1


def test_soft_preferences_do_not_invent_items():
    baseline = recommend_items(CATALOG, "noodles", filters=SearchFilters(kind="recipe"), limit=100)
    preferred = recommend_items(
        CATALOG, "noodles", filters=SearchFilters(kind="recipe"), limit=100,
        preferences=RecommendationPreferences(cuisines=("Japanese",), preference_strength=1.0),
    )
    assert {row.item.item_id for row in baseline.results} == {
        row.item.item_id for row in preferred.results
    }
    for row in preferred.results:
        if row.matched_cuisines:
            assert row.score > row.retrieval_score


def test_exclusion_and_empty_results():
    no_p001 = recommend_items(
        CATALOG, "spicy tofu", preferences=RecommendationPreferences(
            excluded_item_ids=("p001",),
        ),
    )
    assert "p001" not in {row.item.item_id for row in no_p001.results}
    no_match = recommend_items(CATALOG, "zzzxxyyy", filters=SearchFilters(kind="recipe"))
    assert no_match.status == "no_retrieval_matches"
    assert no_match.eligible_items == 6
    assert not no_match.results
    with pytest.raises(ValueError, match="unknown IDs"):
        recommend_items(CATALOG, "spicy", preferences=RecommendationPreferences(
            excluded_item_ids=("not-real",),
        ))


def test_preference_validation_and_shared_service_api():
    with pytest.raises(ValueError, match="preference_strength"):
        RecommendationPreferences(preference_strength=float("nan"))
    with pytest.raises(ValueError, match="distinct"):
        RecommendationPreferences(cuisines=("Japanese", "japanese"))
    service = DiscoveryService(CATALOG)
    assert service.recommend("spicy tofu").as_dict() == recommend_items(CATALOG, "spicy tofu").as_dict()


def test_cli_json(capsys):
    from savoroute.cli import main

    assert main(["recommend", "spicy tofu", "--kind", "recipe", "--diet", "vegan",
                 "--prefer-cuisine", "Japanese", "--json"]) == 0
    response = json.loads(capsys.readouterr().out)
    assert response["catalog_synthetic"] is True
    assert response["status"] == "ok"
    assert response["results"][0]["item_id"] == "p001"
    assert response["results"][0]["matched_preferred_cuisines"] == ["Japanese"]
    assert "not verified" in response["limitations"]


def test_explanation_is_limited_to_recorded_evidence():
    response = recommend_items(
        CATALOG, "spicy tofu", filters=SearchFilters(kind="recipe"),
        preferences=RecommendationPreferences(cuisines=("Japanese",)),
    )
    top = response.results[0].as_dict()
    assert "bm25 rank 1" in top["explanation"]
    assert "Japanese" in top["explanation"]
    assert "synthetic_demo" in top["explanation"]
    assert response.as_dict()["applied_filters"]["kind"] == "recipe"
    assert "probability" not in str(top)
