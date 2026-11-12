# Development roadmap

Each milestone adds reusable Python functionality, tests, a corresponding Jupyter notebook, and CLI support where applicable. Application interfaces are introduced only after the underlying services exist.

| Stage | Scope | Status |
| --- | --- | --- |
| 0 · Foundation | Canonical catalog, lexical retrieval, evaluation, CLI, notebooks 00–03 | Complete |
| 1a · Text ingestion | Source-batch validation, labeled extraction, model extraction protocol, field evidence, catalog admission, notebook 04 | Complete; live model calls unverified |
| 1b · Source acquisition | Bounded OSM snapshot acquisition, direct tag mapping, duplicate review, extraction comparison harness, notebook 05 | Implemented offline; live fetch unverified |
| 1c · Source identity and updates | Registry, explicit source links, idempotent OSM updates, conflict review, notebook 06 | Implemented offline |
| 1d · Versioning and identity evaluation | Element-version ordering, annotation worksheet, pairwise candidate benchmark, notebook 07 | Implemented offline; independent real-data evaluation pending |
| 2a · Local media | Bounded image ingestion, normalized storage, hashes, source/rights metadata, notebook 08; optional joint CLIP adapter | Implemented offline; real model inference unverified |
| 2b · Multimodal embeddings | Versioned JSON vector index, exact cosine search, optional CLIP execution, labeled cross-modal evaluation, notebook 09 | Implemented; real-model inference and real-world evaluation unverified |
| 3a · Item-level retrieval | Weighted BM25/text-vector/image-vector rank fusion, item deduplication, hard metadata filters, item-level benchmark, notebook 10 | Implemented offline; pretrained quality not established |
| 3b · Persistent retrieval | SQLite vector bundles, optional FAISS HNSW, synthetic latency and 42-query challenge, notebook 11 | Implemented; real-data labeling and FAISS runtime validation pending |
| 4 · Recommendations | Binary relevance annotation workflow and deterministic catalog-grounded recommendations; notebook 12 | Implemented offline; independent real-world annotation pending |
| 4b · Real-data study preparation | Frozen OSM provenance, split checks, reviewer references, baseline reports; notebook 13 | Implemented; independent real annotation outstanding |
| 5a · HTTP interface | Versioned read-only API, catalog browsing, shared discovery/recommendations, OpenAPI, notebook 14 | Implemented locally; production hardening outstanding |
| 5b · Agent and web interfaces | MCP tools, responsive web application | Planned |
| 6 · Deployment | Operating limits, end-to-end tests, reproducible public demonstration | Planned |

## Completed ingestion work

Stage 1a reads a bounded local source batch, extracts supported catalog fields, attaches exact text quotations, and checks that each extracted value occurs within its quoted source span. It derives a stable item ID from the source ID, checks admission against catalog schema v1, and writes canonical catalog and provenance JSON files. OpenAI Responses and Ollama adapters implement the existing text-generation protocol. Network integrations have not been validated with provider credentials.

Stage 1b provides a bounded Overpass client, an OSM JSON importer, and a review queue for possible duplicate establishments. Catalog IDs are currently source-derived, so they are not yet independent entity identities. Field-level evaluation compares text-extraction provenance against reference labels. The included synthetic labels do not measure out-of-sample extraction quality.

Stage 1c keeps catalog schema v1 and records source identities in a separate registry. An exact source key can update its source-owned item; possible duplicates require review, and other-provider links are explicitly recorded without merging fields. The system keeps existing item IDs and media associations. Source removal is not inferred from bounded snapshots. See [entity identities and updates](entity-identity-and-updates.md).

Stage 1d adds OSM metadata-aware reconciliation and pairwise evaluation of the same blocking rule used in synchronization. The worksheet generator prepares bounded OSM snapshots for manual labeling; it does not assign truth labels. The included annotated sample is fictional. An independently annotated real benchmark, sampling design, inter-annotator agreement, and licensing review are still outstanding. See [identity candidate evaluation](identity-benchmark.md).

## Application scope

The intended web application uses the same catalog, retrieval, and recommendation services as the notebooks and CLI. Its first flows are search, filtering, and item detail. Image search and guided recommendations follow the corresponding package implementations. The native mobile client has no assigned framework or development milestone.

## Local image processing

Stage 2a validates explicit local file references and exports normalized RGB PNG assets with source and output SHA-256 hashes. Output `catalog.json` uses relative asset URIs and retains catalog schema v1. `provenance.json` records declared source rights; it does not verify permissions. The current command exports a new directory from a catalog without pre-existing media. Image discovery and external fetching are separate concerns. See [image ingestion](media-ingestion.md).

## v0.13.0 — Local MCP adapter (implemented)

Six read-only, stdio-only MCP tools reuse HTTP v1's in-process services,
validation, error handling, provenance, and preference constraints. Remote
MCP/Streamable HTTP deployment is not part of this milestone. See
[local MCP design](mcp-server.md) and [ADR 0009](adr/0009-local-mcp-adapter.md).

Next: a deliberate user-facing web experience, deployment/security design,
and independently reviewed real-world relevance measurements.


## Milestone 4 — Local-first web app (v0.14.0)

- Ship a browser application bundled in the Python wheel, sharing the existing HTTP v1 read-only API.
- Include interactive query/filter controls, recommendation preferences, result evidence, provenance, catalog paging and item details, responsive layout and accessibility measures.
- Preserve the already validated local stdio MCP boundary and versioned HTTP contracts.
- Keep real-world annotation, deployed authentication, rate limits and live availability outside the scope of this release.

Next: evaluate the OSM study with independent human labels, harden deployment only after product needs are clear, and expand the UI with validated data such as genuine photos or menus subject to rights and provenance.
