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

The retrieval demo uses a bundled JSON fixture. No SQL database, embedding index, image loader, HTTP server, MCP server, or application client is implemented.

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

The diagram includes implemented ingestion and catalog components as well as planned retrieval and application interfaces. SQLite is the initial candidate for persistent canonical records; index storage will be selected after the embedding and retrieval experiments. Any text-only and joint text/image embedding spaces will be indexed and scored separately. Cross-index fusion will operate on canonical item IDs, not on uncalibrated raw similarity scores.

The API and MCP interfaces will call shared application services. Model credentials and data access policy will remain server-side. A responsive web client is the first application target; a native mobile client is not yet scoped.

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
