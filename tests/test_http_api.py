"""HTTP contract tests. No network listeners, model downloads or external services."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from savoroute.api.app import create_app
from savoroute.cli import main
from savoroute.data.catalog import catalog_to_dict, load_catalog
from savoroute.retrieval.fusion import FusionWeights
from savoroute.retrieval.lexical import SearchFilters
from savoroute.retrieval.vector import build_vector_index, write_vector_index
from savoroute.services.discovery import DiscoveryService
from savoroute.services.recommendation import RecommendationPreferences


@pytest.fixture
def client():
    with TestClient(create_app()) as instance:
        yield instance


def test_liveness_metadata_and_versioned_schema(client):
    assert client.get("/healthz").json() == {"status": "ok", "api_version": "v1"}
    metadata = client.get("/v1/meta")
    assert metadata.status_code == 200
    assert metadata.json()["package_version"] == "0.18.0"
    assert metadata.json()["catalog_synthetic"] is True
    assert metadata.json()["catalog_items"] == 12
    assert metadata.json()["index_backend"] == "none"
    assert metadata.json()["server_encoder_enabled"] is False
    schema = client.get("/openapi.json").json()
    assert schema["openapi"].startswith("3.")
    assert "/v1/search" in schema["paths"]
    assert "/v1/rank" in schema["paths"]
    assert "/v1/recommend" in schema["paths"]
    assert "/v1/items/{item_id}" in schema["paths"]


def test_catalog_browse_and_details(client):
    catalog = load_catalog()
    response = client.get("/v1/items", params={"limit": 3, "offset": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == len(catalog.items)
    assert body["offset"] == 2 and body["limit"] == 3
    assert [item["item_id"] for item in body["items"]] == [
        item.item_id for item in catalog.items[2:5]
    ]
    item = client.get("/v1/items/p001").json()
    assert item["source"] == catalog.get("p001").source
    assert item["description"] == catalog.get("p001").description
    assert client.get("/v1/items/unknown-item").status_code == 404
    missing = client.get("/v1/items/unknown-item").json()
    assert missing["error"]["code"] == "not_found"
    filtered = client.get("/v1/items", params={"kind": "recipe", "cuisine": "Japanese"})
    assert filtered.status_code == 200
    assert all(item["kind"] == "recipe" for item in filtered.json()["items"])
    assert all("Japanese" in item["cuisines"] for item in filtered.json()["items"])


def test_search_uses_exact_existing_service_not_a_copy(client):
    service = DiscoveryService(load_catalog())
    request = {"query": "spicy tofu noodles", "filters": {"kind": "recipe"}, "limit": 3}
    response = client.post("/v1/search", json=request)
    assert response.status_code == 200
    wire = response.json()
    expected = service.search("spicy tofu noodles", filters=SearchFilters(kind="recipe"), limit=3)
    assert [row["item"]["item_id"] for row in wire["results"]] == [
        row.item.item_id for row in expected
    ]
    assert [row["score"] for row in wire["results"]] == [row.score for row in expected]
    assert wire["results"][0]["method"] == "bm25"
    assert wire["catalog_synthetic"] is True
    assert "not verified" in wire["limitations"]
    overlap = client.post("/v1/search", json={**request, "method": "overlap"})
    assert overlap.status_code == 200
    assert all(row["method"] == "overlap" for row in overlap.json()["results"])


def test_rank_and_recommend_delegate_to_same_domain_logic(client):
    service = DiscoveryService(load_catalog())
    request = {"query": "spicy tofu noodles", "filters": {"kind": "recipe"}}
    rank = client.post("/v1/rank", json=request)
    assert rank.status_code == 200
    body = rank.json()
    assert body["mode"] == "bm25_only"
    expected = service.rank(
        "spicy tofu noodles", filters=SearchFilters(kind="recipe"),
        weights=FusionWeights(bm25=1, text=0, image=0),
    )
    assert [r["item"]["item_id"] for r in body["results"]] == [
        r.item.item_id for r in expected
    ]
    assert body["results"][0]["evidence"][0]["source"] == "bm25"
    rec_request = {
        **request,
        "preferences": {"cuisines": ["Japanese"], "preference_strength": 0.6},
    }
    rec = client.post("/v1/recommend", json=rec_request)
    assert rec.status_code == 200
    expected_rec = service.recommend(
        "spicy tofu noodles", filters=SearchFilters(kind="recipe"),
        preferences=RecommendationPreferences(cuisines=("Japanese",), preference_strength=0.6),
        weights=FusionWeights(1, 0, 0),
    )
    assert rec.json()["results"] == expected_rec.as_dict()["results"]
    assert rec.json()["status"] == "ok"
    assert "catalog" in rec.json()["results"][0]["explanation"].lower()


def test_hard_filters_exclusions_and_no_match(client):
    disallowed = client.post("/v1/recommend", json={
        "query": "noodles", "filters": {"kind": "restaurant", "dietary_tags": ["vegan"]},
    })
    assert disallowed.status_code == 200
    assert disallowed.json()["status"] == "no_eligible_items"
    assert not disallowed.json()["results"]
    excluded = client.post("/v1/recommend", json={
        "query": "spicy tofu", "preferences": {"excluded_item_ids": ["p001"]},
    })
    assert excluded.status_code == 200
    assert "p001" not in {row["item_id"] for row in excluded.json()["results"]}
    no_match = client.post("/v1/search", json={"query": "zzzxxyyyy"})
    assert no_match.status_code == 200 and no_match.json()["results"] == []


@pytest.mark.parametrize("payload", [
    {"query": ""},
    {"query": "   "},
    {"query": "a" * 501},
    {"query": "pasta", "limit": 0},
    {"query": "pasta", "limit": 101},
    {"query": "pasta", "limit": True},
    {"query": "pasta", "filters": {"kind": "invalid"}},
    {"query": "pasta", "filters": {"max_price_tier": 9}},
    {"query": "pasta", "filters": {"dietary_tags": [""]}},
    {"query": "pasta", "unknown_argument": "secret-private-data"},
])
def test_validation_returns_422_without_echoing_private_payload(client, payload):
    response = client.post("/v1/search", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert "secret-private-data" not in response.text
    assert response.json()["error"]["details"]


def test_list_validation_and_error_codes(client):
    assert client.get("/v1/items", params={"limit": -1}).status_code == 422
    assert client.get("/v1/items", params={"max_price_tier": 9}).status_code == 422
    invalid = client.get("/v1/items", params={"cuisine": " "})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "bad_request"
    assert client.get("/v1/items", params={"offset": 100_000}).json()["items"] == []


def test_preference_invalid_and_unrecognized_exclusion(client):
    duplicate = client.post("/v1/recommend", json={
        "query": "pasta", "preferences": {"cuisines": ["Italian", "italian"]},
    })
    assert duplicate.status_code == 422
    unknown = client.post("/v1/recommend", json={
        "query": "pasta", "preferences": {"excluded_item_ids": ["not-in-catalog"]},
    })
    assert unknown.status_code == 400
    assert unknown.json()["error"]["code"] == "bad_request"
    assert client.post("/v1/recommend", json={
        "query": "pasta", "preferences": {"preference_strength": 4},
    }).status_code == 422


def test_index_configuration_is_explicit_and_fails_closed(client):
    assert client.post("/v1/rank", json={
        "query": "noodles", "query_vector": [0.2, 0.8],
    }).status_code == 400
    assert client.post("/v1/rank", json={
        "query": "noodles", "weights": {"bm25": 1, "text": 1, "image": 0},
    }).status_code == 400
    assert client.post("/v1/rank", json={
        "query": "noodles", "weights": {"bm25": 0, "text": 0, "image": 0},
    }).status_code == 422
    assert client.post("/v1/rank", json={
        "query": "noodles", "query_vector": [True, 2.0],
    }).status_code == 422
    assert client.post("/v1/rank", json={
        "query": "noodles", "query_vector": [1.0] * 4097,
    }).status_code == 422
    with pytest.raises(ValueError, match="catalog_path"):
        create_app(index_path="fake-vector-index.json")
    with pytest.raises(ValueError, match="encoder"):
        create_app(encoder=FixtureEncoder())


def test_auth_is_opt_in_and_constant_time(client):
    assert client.get("/v1/meta").status_code == 200
    with TestClient(create_app(api_key="s3cr3t-test")) as secure:
        assert secure.get("/healthz").status_code == 200
        missing = secure.get("/v1/meta")
        assert missing.status_code == 401
        assert missing.json()["error"]["code"] == "unauthorized"
        assert missing.headers["www-authenticate"] == "APIKey"
        assert secure.get("/v1/meta", headers={"X-API-Key": "wrong"}).status_code == 401
        assert secure.get("/v1/meta", headers={"X-API-Key": "s3cr3t-test"}).status_code == 200
        assert secure.post("/v1/search", json={"query": "noodles"}).status_code == 401
        assert secure.post("/v1/search", json={"query": "noodles"},
                           headers={"X-API-Key": "s3cr3t-test"}).status_code == 200
        assert "s3cr3t-test" not in secure.get("/openapi.json").text
        schemes = secure.get("/openapi.json").json()["components"]["securitySchemes"]
        assert any(value.get("name") == "X-API-Key" for value in schemes.values())
    with pytest.raises(ValueError, match="api_key"):
        create_app(api_key="  ")


class FixtureEncoder:
    model_id = "api-test-model"
    embedding_space_id = "api-test-embedding-space"

    def embed_texts(self, texts):
        return [[1.0, 0.0] if "noodle" in text.casefold() else [0.0, 1.0]
                for text in texts]

    def embed_images(self, paths):
        return [[0.0, 1.0] for _path in paths]


@pytest.fixture
def indexed_api(tmp_path):
    catalog = load_catalog()
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog_to_dict(catalog)), encoding="utf-8")
    index_path = tmp_path / "index.json"
    index = build_vector_index(catalog, tmp_path, FixtureEncoder(), include_images=False)
    write_vector_index(index, index_path)
    return catalog_path, index_path


def test_explicit_vector_queries_use_existing_index(indexed_api):
    catalog_path, index_path = indexed_api
    with TestClient(create_app(catalog_path=catalog_path, index_path=index_path)) as client:
        meta = client.get("/v1/meta").json()
        assert meta["index_backend"] == "json"
        assert meta["server_encoder_enabled"] is False
        lexical = client.post("/v1/rank", json={"query": "noodles"})
        assert lexical.status_code == 200
        assert lexical.json()["mode"] == "bm25_only"
        hybrid = client.post("/v1/rank", json={
            "query": "noodles", "query_vector": [1.0, 0.0],
            "weights": {"bm25": 1, "text": 1, "image": 0},
        })
        assert hybrid.status_code == 200
        assert hybrid.json()["mode"] == "hybrid"
        assert any(any(e["source"] == "text" for e in hit["evidence"])
                   for hit in hybrid.json()["results"])
        assert client.post("/v1/rank", json={
            "query": "noodles", "query_vector": [1.0, 0.0, 0.0],
            "weights": {"bm25": 0, "text": 1, "image": 0},
        }).status_code == 400
        rec = client.post("/v1/recommend", json={
            "query": "noodles", "query_vector": [1.0, 0.0],
            "weights": {"bm25": 0, "text": 1, "image": 0},
        })
        assert rec.status_code == 200
        assert rec.json()["results"]
        assert all("text" in [e["source"] for e in hit["retrieval_evidence"]]
                   for hit in rec.json()["results"])


def test_encoder_must_match_and_client_vectors_are_mutually_exclusive(indexed_api):
    catalog_path, index_path = indexed_api
    bad_encoder = FixtureEncoder()
    bad_encoder.model_id = "wrong-model"
    with pytest.raises(ValueError, match="identity"):
        create_app(catalog_path=catalog_path, index_path=index_path, encoder=bad_encoder)
    with TestClient(create_app(catalog_path=catalog_path, index_path=index_path,
                               encoder=FixtureEncoder())) as client:
        metadata = client.get("/v1/meta").json()
        assert metadata["server_encoder_enabled"] is True
        assert client.post("/v1/rank", json={"query": "noodles"}).status_code == 200
        assert client.post("/v1/rank", json={"query": "noodles",
                                             "query_vector": [1, 0]}).status_code == 400


def test_modified_catalog_rejected_at_application_creation(indexed_api):
    catalog_path, index_path = indexed_api
    catalog = json.loads(catalog_path.read_text())
    catalog["items"][0]["title"] = "Altered name"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="catalog differs"):
        create_app(catalog_path=catalog_path, index_path=index_path)


def test_cli_has_opt_in_server_command(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["api", "serve", "--help"])
    assert exc.value.code == 0
    assert "--catalog" in capsys.readouterr().out


def test_server_refuses_unprotected_network_exposure(monkeypatch):
    from savoroute.api.server import serve

    monkeypatch.delenv("SAVOROUTE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="non-loopback"):
        serve(host="0.0.0.0")
    with pytest.raises(ValueError, match="port"):
        serve(port=99999)
    # No actual server started.


def test_serve_command_uses_explicit_app_without_starting_real_socket(monkeypatch, tmp_path):
    import uvicorn

    from savoroute.api.server import serve

    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog_to_dict(load_catalog())), encoding="utf-8")
    received = {}

    def intercept(app, *, host, port, reload, access_log):
        received["host"] = host
        received["port"] = port
        received["reload"] = reload
        received["access_log"] = access_log
        with TestClient(app) as client:
            received["metadata"] = client.get("/v1/meta").json()

    monkeypatch.setattr(uvicorn, "run", intercept)
    monkeypatch.setenv("SAVOROUTE_API_KEY", "nonempty-test-key")
    serve(catalog=catalog_path, host="127.0.0.1", port=9191)
    assert received["host"] == "127.0.0.1" and received["port"] == 9191
    assert received["reload"] is False
    # A configured API key must protect catalog metadata.
    assert received["metadata"]["error"]["code"] == "unauthorized"
