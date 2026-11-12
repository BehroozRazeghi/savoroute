# Architecture

## Retrieval foundation (`0.1.0`)

```text
Jupyter notebooks ─────────┬──> catalog loader / validator ──> domain records
                            ├──> DiscoveryService ────────────> lexical retrieval
                            └──> evaluate_search ─────────────> lexical retrieval
CLI ────────────────────────┤
                            └──> catalog loader / validator

JSON demo fixtures ──> catalog loader ──> immutable Catalog, CatalogItem, MediaAsset
```

`src/savoroute/domain` defines the records. `data/catalog.py` parses the catalog and checks types, keys, IDs and media references. `retrieval/lexical.py` applies exact metadata filters and ranks eligible items. `evaluation/retrieval.py` runs catalog-bound relevance judgments. `services/discovery.py` exposes the search operation; the CLI also calls the catalog loader and evaluator directly. Provider protocols are defined; text-generation implementations are described below.

The lexical demo uses bundled fictional JSON records. The local-media pipeline, exact JSON vector index, persistent SQLite vector store, and item-level RRF implementation are separate modules. The catalog remains JSON-backed; a local, read-only HTTP adapter is implemented in v0.12.0, but there is no MCP server or application client.

## Data and retrieval

Each restaurant or recipe has a unique `item_id`. Media records, when present, refer to that ID. The JSON catalog is authoritative for the offline demo; retrieval results retain the source item rather than generating a replacement record.

The search methods use a simple English alphanumeric tokenizer. Weighted overlap compares distinct query terms against selected item fields. BM25 is calculated over a concatenated document with repeated title and cuisine text; corpus statistics are computed from the complete supplied catalog before filtering. This is not BM25F, and it is not semantic search.

Metadata filters use exact, case-insensitive values for cuisine, location, and dietary tags, and an integer bound for price tier. A missing price tier does not satisfy a maximum-price filter. Dietary tags are catalog metadata, not verified allergen information.

## Intended system

```text
licensed sources / submitted data
                │
        ingestion and extraction
                │
       validation and provenance
                │
      canonical records + media
                │
      text and image processing
                │
   lexical / vector candidate search
                │
     constraints and item-ID fusion
                │
        recommendation service
                │
    ┌───────────┼────────────┐
   CLI       HTTP API     MCP tools
                 │
            web / PWA
                 │
       optional native client
```

The diagram includes implemented ingestion, retrieval, recommendation, and HTTP components, alongside planned MCP and application interfaces. The canonical catalog remains JSON-backed. Stage 2b introduced a bounded JSON-based exact cosine index; stage 3a added item-level fusion. Stage 3b adds immutable SQLite vector bundles and an optional FAISS HNSW approximate-search implementation, retaining the JSON index as a reference. Larger-scale lexical indexing and independent real-world evaluation remain future work. Any text-only and joint text/image embedding spaces will be indexed and scored separately. Cross-source fusion operates on canonical item IDs and rank positions rather than uncalibrated raw similarity scores.

The HTTP interface calls shared application services; the MCP interface is planned. Model credentials and data access policy will remain server-side. A responsive web client is the first application target; a native mobile client is not yet scoped.

## MCP compatibility

The MCP `2026-07-28` specification deprecates Roots, Sampling, and Logging but retains them during the deprecation period. The planned MCP interface will not depend on those capabilities. Protocol and SDK compatibility will be checked when implementation begins.

Reference: [MCP 2026-07-28 changelog](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/changelog.mdx).

## Text ingestion (`0.2.0`)

```text
local JSON source batch
        │
 source-batch validation / normalized text
        │
 labeled extractor OR TextGenerator + model extractor
        │
 JSON contract + verbatim quote validation
        │
 immutable CatalogItem candidates
        │
 canonical schema-v1 admission
        │
 catalog JSON + field-evidence JSON
```

`ingestion/sources.py` owns source validation, timestamps, and normalized text hashes. `ingestion/extraction.py` owns both extraction strategies and the evidence validator. `services/ingestion.py` admits validated items through the existing catalog contract. Source-specific evidence is kept in a sidecar, leaving existing retrieval and benchmark APIs unchanged. All output writes are local; model providers are opt-in. See [text ingestion](ingestion.md).

## Source reconciliation (`0.4.0`)

`identity/registry.py` maps provider source keys to existing catalog items without changing catalog schema v1. `services/osm_sync.py` admits new records, updates uniquely bound OSM-owned records, and records decisions for ambiguous cases. A digest of the last source-managed item prevents unreviewed overwrites of external catalog edits. Records absent from bounded snapshots are retained. The notebook and CLI use the same reconciliation functions. See [identity and updates](entity-identity-and-updates.md).

## Local media ingestion (`0.6.0`)

`media/ingestion.py` reads a versioned local manifest, checks catalog item associations and declared rights metadata, decodes bounded image inputs, and exports RGB PNG assets. The output includes a catalog using relative media paths and an explicit provenance file. The export is created as a new directory so an existing catalog is not modified. The optional CLIP adapter implements the joint image/text embedding protocol without making an embedding-model dependency part of ingestion. See [image ingestion](media-ingestion.md).

## Joint embeddings and exact search (`0.7.0`)

`retrieval/vector.py` builds and validates a versioned JSON index of text records (`text:<item_id>`) and local image records (`image:<media_id>`). It uses a single `JointTextImageEmbedder` with one declared embedding-space identity, unit-normalizes vectors, and records an input SHA-256 digest for each record. The CLI verifies both catalog consistency and indexed image hashes before searching. Queries are ranked by exact cosine similarity; filters and item-level deduplication are explicit.

`evaluation/multimodal.py` evaluates labeled text-to-image and image-to-image queries. The provided synthetic benchmark contains image self-matches and is intended only for interface validation. Real model inference and independent real-world judgments have not been verified. Item-level fusion and persistent vector indexing are implemented in later milestones. See [vector index](vector-index.md).

## Persistent vector retrieval (`0.9.0`)

`retrieval/dense.py` stores source IDs, metadata, and float32 embeddings in an immutable SQLite bundle. Optional FAISS HNSW uses ordinals mapped back through SQLite; the same `search_fused()` service accepts JSON or dense backends. Backend latency and exact-agreement experiments are implemented in `evaluation/dense.py`. The SQLite exact scan remains linear, and FAISS inference/latency require validation on a machine with the optional dependency installed. See [persistent vector retrieval](dense-index.md) and [relevance annotation](relevance-annotation.md).

## Relevance review and recommendation service (`0.10.0`)

`evaluation/annotations.py` constructs bounded exhaustive query–item workbooks against a frozen catalog fingerprint, prepares separate reviewer sheets and validates explicit merge/adjudication decisions, and exports development/test judgments plus an audit. The code does not infer relevance labels or verify the independence of human reviewers. See [relevance workflow](relevance-workflow.md).

`services/recommendation.py` reranks the canonical items returned by `retrieval/fusion.py`, after deterministic hard filters, using a bounded multiplier for catalog-backed soft preferences. `DiscoveryService.recommend()` and the CLI invoke the same implementation. The returned explanation, source fields and retrieval ranks are deterministic; no external LLM call is used. Restaurant hours, prices, ingredient completeness, and allergen safety are not verified. See [grounded recommendations](grounded-recommendations.md).

## Versioned HTTP interface (`0.12.0`)

`api/app.py` exposes a `create_app()` factory using FastAPI and versioned Pydantic
contracts. Catalog and optional trusted vector index are loaded at construction,
not from request-controlled paths. All search, ranking and recommendation routes
delegate to `DiscoveryService` without changing score or evidence semantics.
`api/server.py` starts a loopback development listener by default; an optional API
key is required on non-loopback binding. This does not replace TLS, rate limits,
privacy policy or operational safeguards for public hosting. See [HTTP API v1](http-api.md)
and [ADR 0008](adr/0008-http-adapter-with-shared-services.md).

## Local MCP adapter (v0.13.0)

The optional MCP Python SDK v2 server runs on **stdio**, with six fixed
read-only tools. Calls pass through `CatalogBridge`, which invokes the
versioned FastAPI application using `httpx.ASGITransport` in the same process.
This shares the HTTP validation and serialization logic; the HTTP and MCP
adapters both end in `DiscoveryService` and its established retrieval/ranking
implementations. Catalog and compatible index are fixed and validated at
server creation; MCP callers cannot select files or network endpoints.
See [ADR 0009](adr/0009-local-mcp-adapter.md).
