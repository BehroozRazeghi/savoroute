"""Live discovery is opt-in, strictly filtered, source-labeled and separately rate-limited."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from savoroute.ai.provider import ProviderUnavailable
from savoroute.api.app import create_app
from savoroute.live.contracts import LiveDiscoveryInput, ProposedResults, WebRestaurant
from savoroute.live.provider import OpenAIWebSearchProvider
from savoroute.live.validation import filter_source_leads

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "data/real/boston-osm-2026-11.json"


def _payload(**kwargs):
    return {
        "query": "kebab", "cuisine": "Persian", "city": "Boston",
        "region": "MA", "country": "", "consent_remote_processing": True, **kwargs,
    }


class FakeLiveProvider:
    name = "mock-web"

    def __init__(self, results=None, fail=False):
        self.calls = []
        self.results = results or []
        self.fail = fail

    async def search(self, request):
        self.calls.append(request)
        if self.fail:
            raise ProviderUnavailable("Provider details must not leak")
        return self.results


def web_restaurant(*, name="Example Persian", city="Boston", cuisine="Iranian", url="https://example.org/a"):
    return WebRestaurant(name=name, city=city, region="MA", country="",
                         cuisine=cuisine, source_url=url,
                         source_title="Example source")


def test_live_disabled_by_default_and_catalog_still_works():
    with TestClient(create_app(catalog_path=REAL)) as client:
        assert client.get("/v1/live/status").json()["enabled"] is False
        response = client.post("/v1/live/discover", json=_payload())
        assert response.status_code == 503
        assert client.get("/v1/items").status_code == 200
        assert client.post("/v1/search", json={"query": "pizza"}).status_code == 200


def test_cuisine_and_city_are_hard_constraints_not_lexical_similarities():
    provider = FakeLiveProvider([
        web_restaurant(name="Example Persian"),
        web_restaurant(name="Italian Candidate", cuisine="Italian"),
        web_restaurant(name="Outside Candidate", city="Cambridge"),
        web_restaurant(name="Bad URL", url="javascript:alert(1)"),
    ])
    with TestClient(create_app(catalog_path=REAL, live_provider=provider)) as client:
        response = client.post("/v1/live/discover", json=_payload())
        assert response.status_code == 200
        data = response.json()
        assert data["catalog_results"] == []  # No invented Persian tags in Boston pilot
        assert [r["name"] for r in data["web_results"]] == ["Example Persian"]
        assert data["web_results"][0]["source_label"] == (
            "web_search_source_not_independently_verified"
        )
        assert data["requested_cuisine"] == "Persian"
        assert "NOT independent" in data["limitations"]
        assert response.headers["cache-control"] == "no-store"
        assert len(provider.calls) == 1


def test_absent_source_evidence_cannot_be_displayed():
    request = LiveDiscoveryInput.model_validate(_payload())
    proposals = ProposedResults.model_validate({"restaurants": [
        {"name": "Grounded Persian", "city": "Boston", "region": "MA", "country": "", "cuisines": ["Iranian"],
         "source_url": "https://directory.example/a"},
        {"name": "Invented URL", "city": "Boston", "region": "MA", "country": "", "cuisines": ["Persian"],
         "source_url": "https://invented.example/a"},
        {"name": "Non-matching cuisine", "city": "Boston", "region": "MA", "country": "", "cuisines": ["Lebanese"],
         "source_url": "https://directory.example/b"},
        {"name": "Outside city", "city": "Cambridge", "region": "MA", "country": "", "cuisines": ["Persian"],
         "source_url": "https://directory.example/c"},
        {"name": "No local web target", "city": "Boston", "region": "MA", "country": "", "cuisines": ["Persian"],
         "source_url": "https://localhost/a"},
    ]})
    observed = [{"url": "https://directory.example/a", "title": "Restaurant listing"},
                {"url": "https://directory.example/b"},
                {"url": "https://directory.example/c"}]
    filtered = filter_source_leads(proposals, request, observed)
    assert len(filtered) == 1
    assert filtered[0].name == "Grounded Persian"
    assert filtered[0].source_title == "Restaurant listing"


def test_missing_consent_blank_constraints_and_invalid_json_never_call_provider():
    provider = FakeLiveProvider()
    for request in (
            {**_payload(), "consent_remote_processing": False},
            {**_payload(), "city": " "},
            {**_payload(), "cuisine": " "},
            {**_payload(), "unexpected": "secret"},
    ):
        with TestClient(create_app(live_provider=provider)) as client:
            response = client.post("/v1/live/discover", json=request)
            assert response.status_code == 422
            assert "secret" not in response.text
    for content, media_type, expected in (
        (b"invalid", "application/json", 422),
        (b"x" * 5000, "application/json", 413),
        (b"{}", "text/plain", 415),
    ):
        with TestClient(create_app(live_provider=provider)) as client:
            assert client.post("/v1/live/discover", content=content, headers={
                "Content-Type": media_type,
            }).status_code == expected
    assert provider.calls == []


def test_failed_provider_does_not_expose_secret_error_or_fallback_to_unrelated():
    with TestClient(create_app(live_provider=FakeLiveProvider(fail=True))) as client:
        response = client.post("/v1/live/discover", json=_payload())
        assert response.status_code == 503
        assert "Provider details" not in response.text


def test_rate_limit_is_an_independent_boundary():
    provider = FakeLiveProvider()
    with TestClient(create_app(live_provider=provider)) as client:
        for _ in range(3):
            assert client.post("/v1/live/discover", json=_payload()).status_code == 200
        fourth = client.post("/v1/live/discover", json=_payload())
        assert fourth.status_code == 429
        assert fourth.headers["retry-after"] == "60"
        assert len(provider.calls) == 3


def test_web_search_provider_requires_real_web_call_and_observed_citation(monkeypatch):

    seen = []

    def mock_handler(request):
        body = json.loads(request.content)
        seen.append(body)
        assert request.url == "https://api.openai.com/v1/responses"
        assert body["tools"] == [{"type": "web_search"}]
        assert body["tool_choice"] == "required"
        assert body["include"] == ["web_search_call.action.sources"]
        assert body["store"] is False
        assert "Persian" in body["input"] and "Boston" in body["input"]
        assert b"test_secret" not in request.content
        return httpx.Response(200, json={
            "status": "completed",
            "output": [
                {"type": "web_search_call", "action": {"type": "search", "sources": [
                    {"url": "https://directory.example/a", "title": "Original listing"},
                ]}},
                {"type": "message", "content": [{"type": "output_text", "text": json.dumps({
                    "restaurants": [
                        {"name": "A Persian Restaurant", "city": "Boston", "region": "MA", "country": "",
                         "cuisines": ["Iranian"], "source_url": "https://directory.example/a"},
                        {"name": "Made-up", "city": "Boston", "region": "MA", "country": "", "cuisines": ["Persian"],
                         "source_url": "https://invented.example/nope"},
                    ],
                })}]},
            ],
        })

    real_client = httpx.AsyncClient

    def mock_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(mock_handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_client)
    provider = OpenAIWebSearchProvider(api_key="test_secret")
    request = LiveDiscoveryInput.model_validate(_payload())
    leads = asyncio.run(provider.search(request))
    assert len(seen) == 1
    assert [entry.name for entry in leads] == ["A Persian Restaurant"]
    assert leads[0].source_url == "https://directory.example/a"


def test_web_search_missing_tool_sources_does_not_make_up_results(monkeypatch):

    real_client = httpx.AsyncClient

    def mock_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(lambda _: httpx.Response(200, json={
            "status": "completed", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps({"restaurants": [
                    {"name": "Invented", "city": "Boston", "region": "MA", "country": "", "cuisines": ["Persian"],
                     "source_url": "https://invented.example/a"},
                ]})},
            ]}],
        }))
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_client)
    provider = OpenAIWebSearchProvider(api_key="test_secret")
    try:
        asyncio.run(provider.search(LiveDiscoveryInput.model_validate(_payload())))
    except ProviderUnavailable:
        pass
    else:
        raise AssertionError("Web search should reject absence of tool evidence")


def test_explicit_region_and_country_do_not_match_other_places():
    request = LiveDiscoveryInput.model_validate({
        **_payload(), "country": "United States",
    })
    proposed = ProposedResults.model_validate({"restaurants": [
        {"name": "Boston MA", "city": "Boston", "region": "Massachusetts",
         "country": "USA", "cuisines": ["Persian"], "source_url": "https://example.org/ma"},
        {"name": "Boston Elsewhere", "city": "Boston", "region": "Lincolnshire",
         "country": "United Kingdom", "cuisines": ["Persian"], "source_url": "https://example.org/uk"},
        {"name": "Wrong US State", "city": "Boston", "region": "New York",
         "country": "United States", "cuisines": ["Persian"], "source_url": "https://example.org/ny"},
    ]})
    sources = [{"url": f"https://example.org/{code}"} for code in ("ma", "uk", "ny")]
    hits = filter_source_leads(proposed, request, sources)
    assert [h.name for h in hits] == ["Boston MA"]


def test_local_catalog_matches_cuisine_alias_only_if_city_is_recorded(tmp_path):
    catalog = json.loads(REAL.read_text(encoding="utf-8"))
    records = catalog["items"][:2]
    assert len(records) == 2
    records[0]["cuisines"] = ["iranian"]
    records[1]["cuisines"] = ["italian"]
    # This record mentions Boston in its address but has no source-recorded city.
    missing_city = dict(records[0])
    missing_city["item_id"] = "uncertain-city-fixture"
    missing_city["city"] = None
    missing_city["city_source"] = None
    missing_city["city_id"] = None
    missing_city["location"] = "Boston city in display address"
    catalog["items"] = [*records, missing_city]
    fixture = tmp_path / "catalog.json"
    fixture.write_text(json.dumps(catalog), encoding="utf-8")
    with TestClient(create_app(catalog_path=fixture, live_provider=FakeLiveProvider())) as client:
        result = client.post("/v1/live/discover", json={
            **_payload(), "query": "",
        })
        assert result.status_code == 200
        displayed = result.json()["catalog_results"]
        assert [row["item_id"] for row in displayed] == [records[0]["item_id"]]


def test_live_routes_keep_existing_api_key_authorization():
    with TestClient(create_app(api_key="server-only-token", live_provider=FakeLiveProvider())) as client:
        assert client.get("/v1/live/status").status_code == 401
        assert client.post("/v1/live/discover", json=_payload()).status_code == 401
        assert client.get("/v1/live/status", headers={
            "X-API-Key": "server-only-token",
        }).json()["enabled"] is True
