# ADR 0008: Versioned read-only HTTP adapter

Status: Accepted for Savoroute v0.12.0

## Context

The project has reusable Python services for lexical retrieval, fused ranking,
grounded recommendations, and evaluation. The browser application and MCP adapter
need a stable, testable boundary. Rewriting retrieval in HTTP endpoints would create
behavioral drift from notebooks and CLI.

## Decision

1. Expose `/v1` routes implemented with an optional FastAPI dependency.
2. Load the canonical catalog and optional trusted vector index once at app
   construction. Validate index/catalog compatibility before listening.
3. Do not accept per-request filenames, URLs, model configuration, downloads, or
   data mutations. Keep file ingestion and empirical-study tooling out of HTTP.
4. Call `DiscoveryService` for all ranking and recommendation operations. Keep
   source provenance and limitation statements in API results.
5. Validate bounded input/output contracts, refuse unknown fields, and maintain
   a schema-derived OpenAPI document. Keep internal errors distinct from user input.
6. Bind only to loopback by default. Offer an optional API key for local prototypes;
   prohibit unauthenticated non-loopback binding in the CLI.
7. Default to lexical-only mode. Accept explicitly supplied, precomputed vectors
   only with a configured compatible index; encoder configuration is an advanced
   Python factory integration, not an implicit external download.

## Consequences

- CLI, notebook, HTTP and future MCP remain consumers of the same services.
- Versioned HTTP schemas can evolve independently of catalog schema v1.
- Query vectors are **not authenticated as belonging to the model's embedding
  space**; that remains a trust boundary for client-supplied embeddings.
- Auth, TLS, rate limits, request-body limits, CORS policy, deployment and load
  testing require deliberate production engineering before public access.
- The new HTTP interface does not establish real-world retrieval or restaurant
  recommendation quality. Independent human judgments remain necessary.
