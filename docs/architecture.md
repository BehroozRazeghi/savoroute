# Architecture

Savoroute is a catalog-backed retrieval application. Its Python domain and service layers own record validation, search, ranking, and recommendation. The browser, CLI, HTTP API, MCP server, and notebooks call these implementations; they do not maintain separate ranking models.

```text
Local sources / saved OSM snapshot / explicit media manifests
                         |
                 ingestion and checks
                         |
            canonical JSON catalog + provenance
                         |
        +----------------+-------------------+
        |                                    |
  lexical search                   optional vector index
  (BM25 / overlap)               (text / image; JSON / SQLite)
        |                                    |
        +------------ item-ID fusion -------+
                         |
           filters and preference reranking
                         |
                   DiscoveryService
                         |
              +----------+----------+
              |          |          |
           Python CLI  HTTP v1  MCP stdio
                         |
                    local web UI
```

The diagram shows the retrieval path. Geographic discovery, evidence review, local-media publication, visit suggestions, and human relevance evaluation are separate services operating on catalog-bound inputs.

## Data and identities

- `domain/` defines catalog records and media references. `data/catalog.py` validates JSON and item relationships.
- `identity/` and OSM services maintain source bindings, check updates, and isolate ambiguous associations for review. A missing item in a bounded OSM snapshot is not automatically deleted.
- `evidence/` stores explicitly reviewed claims separately from canonical retrieval fields. Review decisions and declared image licenses do not establish independent factual or legal verification.
- Review and evaluation artifacts carry catalog or study fingerprints. A hash checks identity and integrity; it does not prove source accuracy or reviewer independence.

## Retrieval and ranking

- `retrieval/lexical.py` implements a simple English alphanumeric tokenizer, weighted term overlap, and BM25 over concatenated fields with repeated title/cuisine text. It is **not BM25F** or semantic search.
- `retrieval/vector.py` supports optional shared text/image embeddings and an exact cosine index. `retrieval/dense.py` supports persistent SQLite retrieval and optional FAISS HNSW. The default sample uses no embedding model.
- `retrieval/fusion.py` combines distinct item rankings using weighted reciprocal-rank contributions. Native BM25 and cosine scores are not directly added.
- `services/recommendation.py` applies recorded metadata preferences to retrieved candidates. Its adjustment is a ranking utility, not a probability or evidence of user satisfaction.
- Unknown cuisine, dietary, or price fields do not satisfy corresponding hard filters. Recorded dietary tags are not food-safety assurances.

See [rank fusion](rank-fusion.md) and [recommendation scoring](grounded-recommendations.md) for algorithm definitions.

## Interfaces and trust boundaries

- `cli.py` exposes local ingestion, discovery, review, and evaluation commands.
- `api/app.py` exposes a read-only `/v1` HTTP contract; the server loads operator-selected files at startup. An optional API key is not sufficient to make a deployment publicly secure.
- `mcp/` exposes six read-only tools over local stdio, sharing the HTTP validation path in-process. Remote transport is not supplied.
- `web/` serves HTML/CSS/JavaScript from the same FastAPI process and calls `/v1`. Review pages open explicitly selected files in the browser; they are separate from the discovery interface.
- Geography requires a matching saved OSM snapshot. Distance is straight-line to recorded reference geometry, not routed travel time.

## Evaluation scope

`evaluation/` provides synthetic tests, reviewer-sheet processing, frozen-study integrity checks, baseline comparisons, and query-level bootstrap summaries. The human-review workflow does not create relevance labels automatically. The small Boston OSM pilot is not a demonstrated real-world quality result until independent judgments and adjudication are complete; even then, its query sample limits generalization.

See [statistical evaluation](statistical-relevance-study.md), [design decisions](adr/), and the [quality plan](product-quality-plan.md). Operational security, larger-scale effectiveness, and UX validation remain open work.

## Geographic filtering in v0.21.1

Metadata filters use exact, case-insensitive values for cuisine and dietary tags, and an integer bound for price tier. The legacy `location` filter accepts exact recorded-city equality or exact display-address equality; substring matching is not used. City, region and country fields must be source-grounded, and missing municipalities remain unknown. A missing price tier does not satisfy a maximum-price filter. Dietary tags are catalog metadata, not verified allergen information. See [geographic normalization](geographic-normalization.md).
