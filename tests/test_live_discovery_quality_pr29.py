"""PR #29: geographic consent, relevance, deterministic ranking and evidence links."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, replace
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from savoroute.api.app import create_app
from savoroute.data.catalog import load_catalog
from savoroute.live.contracts import LiveDiscoveryInput, WebRestaurant
from savoroute.live.evaluation import evaluate_dataset
from savoroute.live.provider import OpenAIWebSearchProvider
from savoroute.live.quality import link_and_dedupe, matching_catalog, rank_web
from savoroute.live.validation import place_matches

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "data/real/boston-osm-2026-11.json"


def _request(**changes):
    values = {
        "query": "ghormeh sabzi", "cuisine": "Persian", "city": "Boston",
        "region": "MA", "country": "United States", "geography_scope": "nearby",
        "nearby_cities": ["Cambridge", "Somerville"],
        "consent_remote_processing": True,
    }
    values.update(changes)
    return values


class FakeProvider:
    name = "test-provider"

    def __init__(self, results):
        self.results = results
        self.requests = []

    async def search(self, request):
        self.requests.append(request)
        return self.results


def web(name, city, cuisine="Iranian", region="MA", country="US"):
    return WebRestaurant(name=name, city=city, cuisine=cuisine, region=region,
                         country=country, source_url=f"https://example.org/{name.replace(' ', '-')}",
                         source_title="Cuisine and menu directory")


def test_exact_city_mode_cannot_silently_expand_to_cambridge():
    exact = LiveDiscoveryInput.model_validate({
        **_request(), "geography_scope": "city", "nearby_cities": [],
    })
    assert place_matches("Boston", "MA", "USA", exact)
    assert not place_matches("Cambridge", "MA", "United States", exact)


def test_explicit_nearby_scope_keeps_strict_cuisine_region_and_country():
    provider = FakeProvider([
        web("Boston Iranian", "Boston"),
        web("Cambridge Iranian", "Cambridge"),
        web("Somerville Iranian", "Somerville"),
        web("Newton Iranian", "Newton"),
        web("Other Cuisine", "Cambridge", cuisine="Lebanese"),
        web("Wrong State", "Cambridge", region="NY"),
        web("Wrong Country", "Boston", country="United Kingdom"),
        web("Unknown Country", "Boston", country=""),
    ])
    with TestClient(create_app(catalog_path=REAL, live_provider=provider)) as client:
        response = client.post("/v1/live/discover", json=_request())
    assert response.status_code == 200
    data = response.json()
    assert data["geography_scope"] == "nearby"
    assert data["requested_cities"] == ["Boston", "Cambridge", "Somerville"]
    assert {entry["name"] for entry in data["web_results"]} == {
        "Boston Iranian", "Cambridge Iranian", "Somerville Iranian",
    }
    assert data["catalog_results"] == []  # No source-tagged Persian restaurants in pilot.
    assert len(provider.requests) == 1
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("changes", [
    {"geography_scope": "nearby", "nearby_cities": []},
    {"geography_scope": "nearby", "region": ""},
    {"geography_scope": "nearby", "country": ""},
    {"geography_scope": "city", "nearby_cities": ["Cambridge"]},
    {"nearby_cities": ["Boston"]},
    {"nearby_cities": ["Cambridge", "cambridge"]},
    {"nearby_cities": [f"City {n}" for n in range(13)]},
    {"geography_scope": "10-mile-radius", "nearby_cities": []},
])
def test_invalid_scope_or_ambiguous_cities_rejected_without_web_call(changes):
    with pytest.raises(ValidationError):
        LiveDiscoveryInput.model_validate(_request(**changes))
    provider = FakeProvider([])
    with TestClient(create_app(live_provider=provider)) as client:
        response = client.post("/v1/live/discover", json=_request(**changes))
    assert response.status_code == 422
    assert provider.requests == []


def test_recorded_catalog_cuisine_survives_unverified_dish_preference():
    original = load_catalog(REAL)
    item = next(entry for entry in original.items if entry.city == "Boston")
    item = replace(item, cuisines=("Iranian",), region="MA", country="United States")
    matches = matching_catalog([item], LiveDiscoveryInput.model_validate(_request()))
    assert matches == [item]
    # A missing dish/menu description is not evidence the restaurant lacks that dish.
    assert "ghormeh" not in item.description.lower()


def test_catalog_soft_ranking_prefers_recorded_relevant_text_and_primary_city():
    original = load_catalog(REAL)
    sample = next(entry for entry in original.items if entry.city == "Boston")
    items = [
        replace(sample, item_id="b", title="Iranian Cafe", description="OSM record", cuisines=("Iranian",),
                region="MA", country="USA"),
        replace(sample, item_id="a", title="Persian kebab", description="OSM record", cuisines=("Iranian",),
                region="MA", country="USA"),
        replace(sample, item_id="c", title="Iranian Curry", city="Cambridge",
                description="OSM record", cuisines=("Iranian",), region="MA", country="USA"),
    ]
    request = LiveDiscoveryInput.model_validate(_request(query="kebab"))
    assert [item.item_id for item in matching_catalog(items, request)] == ["a", "b", "c"]


def test_web_soft_ranking_never_reorders_unrelated_cuisine_back_in():
    request = LiveDiscoveryInput.model_validate(_request(query="kebab"))
    ranked = rank_web([
        web("Persian Dining", "Boston"),
        web("Persian Kebab", "Somerville"),
    ], request)
    assert ranked[0].name == "Persian Kebab"


def test_exact_cross_source_identity_links_and_retains_evidence():
    original = load_catalog(REAL)
    source = next(entry for entry in original.items if entry.city == "Boston")
    item = replace(source, title="Persian Garden", item_id="id-42", cuisines=("Persian",),
                   country="United States", region="MA")
    matches, links = link_and_dedupe([item], [
        web("Persian Garden", "Boston"),
        web("Persian Garden", "Cambridge"),
        web("Persian Garden", "Boston", country="United Kingdom"),
        web("Persian Gardens", "Boston"),
    ])
    assert len(matches) == 3
    assert len(links) == 1
    assert links[0].catalog_item_id == "id-42"
    assert links[0].source_url.startswith("https://")


def test_provider_is_restricted_to_explicit_cities_in_web_prompt(monkeypatch):
    real_client = httpx.AsyncClient
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        assert "Cambridge" in body["input"]
        assert "Somerville" in body["input"]
        assert "Boston" in body["input"]
        assert body["store"] is False
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "web_search_call", "action": {"sources": [
                {"url": "https://example.org/restaurant", "title": "Named restaurant"},
            ]}},
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps({
                "restaurants": [{"name": "Cambridge Persian", "city": "Cambridge", "region": "MA",
                                 "country": "United States", "cuisines": ["Iranian"],
                                 "source_url": "https://example.org/restaurant"}],
            })}]},
        ]})

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    hits = asyncio.run(OpenAIWebSearchProvider(api_key="safe-test-key").search(
        LiveDiscoveryInput.model_validate(_request())))
    assert len(seen) == 1
    assert [hit.city for hit in hits] == ["Cambridge"]


def test_synthetic_fixture_is_valid_and_not_claimed_as_real_market_data():
    path = ROOT / "data/sample/live_discovery_synthetic_quality.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["dataset_type"] == "synthetic_regression_fixture"
    assert len(data["cases"]) == 12
    result = evaluate_dataset(data)
    assert result.cases == 12
    assert result.hard_constraint_violation_rate == 0
    assert result.cited_url_coverage == 1
    assert "Synthetic" in result.notes


def test_metrics_detect_unsafe_evidence_and_violation():
    case = {
        "id": "negative", "request": _request(geography_scope="city", nearby_cities=[]),
        "answerable": True, "relevant_ids": ["expected"],
        "results": [
            {"id": "wrong", "city": "Newton", "region": "MA", "country": "US",
             "cuisine": "Italian", "source_url": "javascript:alert(1)"},
        ],
    }
    metrics = evaluate_dataset({"cases": [case]})
    assert metrics.hard_constraint_violation_rate == 1
    assert metrics.cited_url_coverage == 0
    assert metrics.precision_at_5 == 0
    assert metrics.success_at_5_answerable == 0
    assert metrics.correct_abstention_unanswerable is None


def test_evaluation_rejects_missing_annotations():
    with pytest.raises(ValueError, match="answerable"):
        evaluate_dataset({"cases": [{"id": "no-label", "request": _request(),
                                     "results": [], "relevant_ids": []}]})


def test_serialized_metrics_have_no_secrets():
    metrics = evaluate_dataset(json.loads((
        ROOT / "data/sample/live_discovery_synthetic_quality.json"
    ).read_text(encoding="utf-8")))
    assert "api_key" not in str(asdict(metrics)).lower()


def test_unreviewed_100_queries_cannot_be_published_as_quality_measurement():
    path = ROOT / "data/evaluation/live_discovery_100_query_review_template.json"
    dataset = json.loads(path.read_text(encoding="utf-8"))
    assert dataset["dataset_type"] == "unreviewed_100_query_template"
    assert len(dataset["cases"]) == 100
    assert len({case["id"] for case in dataset["cases"]}) == 100
    with pytest.raises(ValueError, match="answerable"):
        evaluate_dataset(dataset)


def test_state_and_country_aliases_preserve_explicit_jurisdiction():
    request = LiveDiscoveryInput.model_validate(_request(
        city="San Diego", region="California", country="USA",
        geography_scope="city", nearby_cities=[],
    ))
    assert place_matches("San Diego", "CA", "United States", request)
    assert not place_matches("San Diego", "MA", "United States", request)
    assert not place_matches("San Diego", "CA", "Mexico", request)
    assert not place_matches("San Diego", "", "USA", request)


def test_review_template_has_valid_explicit_constraints_but_no_truth_labels():
    path = ROOT / "data/evaluation/live_discovery_100_query_review_template.json"
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 100
    assert all(case["answerable"] is None for case in cases)
    for case in cases:
        LiveDiscoveryInput.model_validate({
            **case["request"], "consent_remote_processing": True,
        })
