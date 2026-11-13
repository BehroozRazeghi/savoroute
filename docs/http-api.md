# HTTP API v1 (Savoroute 0.12.0)

## Scope and boundary

The optional FastAPI adapter exposes existing read-only catalog services. It does **not**
perform ingestion, external fetching, model downloads, data mutation, annotation, or
real-time reservation/availability queries. It does not maintain a separate ranking
algorithm. `DiscoveryService.search`, `.rank`, and `.recommend` remain authoritative.

Catalog and optional vector-index paths are chosen by the operator at process startup;
clients cannot supply filesystem paths, source URLs, API credentials, or model IDs.
The default app loads the **fictional** bundled catalog and uses lexical ranking.
No `savoroute.api` import occurs during normal package import or CLI commands.

## Installation and local execution

```bash
python -m pip install -e ".[api,dev,notebooks]"
savoroute api serve --host 127.0.0.1 --port 8000
```

The local OpenAPI document is at `http://127.0.0.1:8000/openapi.json` and interactive
API documentation at `http://127.0.0.1:8000/docs`. This starts a local development
server, not a deployed service.

To use the real OSM pilot **after collecting it separately**:

```bash
savoroute api serve --catalog data/generated/real-pilot/catalog.json
```

This selects the local catalog only; it does not contact OSM or change the frozen
annotation study. The process fails at startup if the catalog is invalid.

### Requests

```bash
curl -sS http://127.0.0.1:8000/healthz
curl -sS http://127.0.0.1:8000/v1/meta
curl -sS 'http://127.0.0.1:8000/v1/items?kind=recipe&limit=5'
curl -sS http://127.0.0.1:8000/v1/items/p001

curl -sS http://127.0.0.1:8000/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"spicy tofu noodles","filters":{"kind":"recipe"},"limit":3}'

curl -sS http://127.0.0.1:8000/v1/rank \
  -H 'Content-Type: application/json' \
  -d '{"query":"spicy tofu noodles","filters":{"kind":"recipe"}}'

curl -sS http://127.0.0.1:8000/v1/recommend \
  -H 'Content-Type: application/json' \
  -d '{"query":"spicy tofu noodles","filters":{"kind":"recipe"},"preferences":{"cuisines":["Japanese"],"preference_strength":0.5}}'
```

## Version-1 routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Basic liveness; no catalog contents or credentials |
| GET | `/v1/meta` | Dataset identity, synthetic flag, index/encoder capabilities |
| GET | `/v1/items` | Filtered catalog browsing, paginated; **not** relevance-ranked |
| GET | `/v1/items/{item_id}` | Canonical catalog item or 404 |
| POST | `/v1/search` | BM25 or overlap via `DiscoveryService.search()` |
| POST | `/v1/rank` | Item-level RRF via `DiscoveryService.rank()` |
| POST | `/v1/recommend` | Catalog-backed recommendations via `DiscoveryService.recommend()` |

JSON requests reject unknown fields (`422`), empty/overlong queries, invalid filters,
non-finite weights, unsupported sizes, duplicate preferences, and non-finite query
vectors. All search and recommendation endpoints enforce `limit <= 100`. Catalog
listing also caps `limit` at 100 and validates pagination bounds. Hard filters are
identical to the Python library: missing attributes do not satisfy a filter.

`/v1/search` returns native lexical scores; `/v1/rank` uses RRF scores;
`/v1/recommend` uses bounded preference reranking. **These are not probabilities,
quality scores or safety guarantees.** Recommendations include source records,
original retrieval ranks, an explanation restricted to stored evidence, and a
limitations statement. Empty results are legitimate HTTP `200` responses, with an
explicit recommendation status. No minimum relevance/abstention threshold is implied.

### HTTP errors

- `400`: logically incompatible request (unknown excluded item, missing configured
  index for vector weights, wrong query-vector dimension).
- `401`: absent/incorrect `X-API-Key` if operator authentication is enabled.
- `404`: unknown catalog item.
- `422`: invalid JSON structure, unknown request properties, invalid field bounds.
- `500`: unexpected server error; details are not returned when debug mode is off.

Expected client errors use `{"error":{"code":"...","message":"..."}}`.
Validation errors additionally contain safe field/type diagnostics, **not** the raw
rejected input. A 500 may use the framework's generic response. Clients should rely
on HTTP codes and versioned fields, not error text.

## Optional prebuilt vector index

```bash
savoroute api serve \
  --catalog data/generated/m2b/media/catalog.json \
  --index data/generated/m2b/vectors.json
```

`--index` also accepts a compatible SQLite or FAISS bundle directory. The operator
must choose a trusted, locally built index. The catalog fingerprint and indexed
media hashes are verified at app construction; mismatches stop startup. FAISS
serialization must not be loaded from untrusted sources.

Without an operator-configured encoder, text requests fall back to **BM25-only** RRF
(`mode: bm25_only`) even if an index is loaded. Clients with an already-compatible
embedding may send `query_vector` and explicit source weights:

```json
{
  "query": "mushroom pasta",
  "query_vector": [0.2, 0.8],
  "weights": {"bm25": 1.0, "text": 1.0, "image": 0.0},
  "limit": 5
}
```

The vector must match the loaded index's dimension and **embedding space**. The
server verifies dimensions but cannot prove that a client produced a vector with
the declared model. Client-vector support is intended for local evaluation and
trusted integrations; untrusted public vector search needs further policy controls.

Python applications can alternatively supply a compatible `JointTextImageEmbedder`
instance when calling `create_app(catalog_path=..., index_path=..., encoder=...)`.
The default `savoroute api serve` command deliberately does not auto-download,
auto-load, or run a model. Image uploads and image-query encoding are not HTTP
routes in v1.

## Access control and operational limitations

The server binds to `127.0.0.1` by default. It reads `SAVOROUTE_API_KEY` from the
environment, if set, and then requires `X-API-Key` on `/v1/*` endpoints. `/healthz`
and the OpenAPI schema remain public; no secret value appears in the schema.

```bash
export SAVOROUTE_API_KEY='replace-with-a-long-random-secret'
savoroute api serve --host 127.0.0.1 --port 8000
curl -H "X-API-Key: $SAVOROUTE_API_KEY" http://127.0.0.1:8000/v1/meta
```

Binding beyond loopback requires a key, but **an API key alone is not secure public
hosting**. Use a TLS-terminating reverse proxy, request-size limits, rate limits,
authentication appropriate to the users, logging/privacy controls, abuse protection,
source-license compliance, and deployment health monitoring before any public launch.
No CORS origins are enabled by default. The dev server is single-process and not
production-hardened. Disk-backed exact retrieval may be slow for large catalogs;
API performance and load testing remain outstanding.

When displaying OSM-derived content, retain © OpenStreetMap contributors
attribution and follow ODbL obligations. The API is not a restaurant reservation
provider and must not imply verified current opening hours, menus, prices, or
allergen safety.

## Reproducibility and tests

The web test suite uses `fastapi.testclient.TestClient` and the bundled fictional
catalog or tiny deterministic test embeddings. There are no real network sockets,
model downloads, or human-labeled relevance results. Install the development extra
(which includes FastAPI and HTTPX), then run:

```bash
python -m pytest -q tests/test_http_api.py
python -m pytest -q
python -m ruff check src tests scripts
```

Notebook 14 runs the same endpoints in process with `TestClient`, without starting
a background server. HTTP routes expose catalog **metadata**, not the frozen study
reviewer annotations; quality evaluation remains a separate workflow.

## Milestone 3: optional OSM source observations (v0.20.0)

When the server is started with `--source-facts` pointing to a catalog-bound
sidecar, `GET /v1/items/{item_id}/source-facts` returns a declared source
reference, snapshot date, raw tag names and bounded values, all explicitly
marked `verification_status=unverified_osm_tags`. Without a sidecar, existing
items return no facts and `not_configured`. An absent item returns HTTP 404;
normal API-key checks apply. The `/v1/meta` response additionally advertises
`source_facts_enabled` and `source_facts_records`. **This new route does not
change `/v1/items`, `/v1/search`, `/v1/rank` or `/v1/recommend`.**

See [source facts and quality audit](data-quality-and-source-facts.md).

### Optional recipe notes (v0.21.0)

`GET /v1/items/{item_id}/recipe-notes` is available when startup configured `--recipe-notes <catalog-digest-bound-json>`. It returns editorial recipe ingredients, preparation steps, a revision-specific source URL, attribution, CC BY-SA license information and review status `source_transcribed_unverified`; requests for unmatched items or when disabled return the standard not-found/disabled response. This endpoint shares the API-key authorization gate, does not retrieve source text over a network, and does **not** assert allergy or food safety verification. Use matching `--catalog`, `--source-facts` and `--recipe-notes` sidecars. See `docs/recipe-curation-m4.md`.
