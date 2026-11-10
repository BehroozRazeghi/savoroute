# Development roadmap

Each milestone adds reusable Python functionality, tests, a corresponding Jupyter notebook, and CLI support where applicable. Application interfaces are introduced only after the underlying services exist.

| Stage | Scope | Status |
| --- | --- | --- |
| 0 · Foundation | Canonical catalog, lexical retrieval, evaluation, CLI, notebooks 00–03 | Complete |
| 1a · Text ingestion | Source-batch validation, labeled extraction, model extraction protocol, field evidence, catalog admission, notebook 04 | Complete; live model calls unverified |
| 1b · Source acquisition | Licensed datasets, supported source adapters, duplicate entity handling, source policy, extraction quality assessment | Next |
| 2 · Multimodal data | Permitted image ingestion, captions, text/image embeddings, reproducible indexes | Planned |
| 3 · Retrieval | Vector search, deterministic filters, item-level fusion, evaluation | Planned |
| 4 · Recommendations | Preference constraints, retrieved evidence, grounded recommendations | Planned |
| 5 · Interfaces | Versioned HTTP API, MCP tools, responsive web application | Planned |
| 6 · Deployment | Operating limits, end-to-end tests, reproducible public demonstration | Planned |

## Completed ingestion work

Stage 1a reads a bounded local source batch, extracts supported catalog fields, attaches exact text quotations, and verifies every extracted value. It derives a stable item ID from the source ID, checks admission against catalog schema v1, and writes canonical catalog and provenance JSON files. OpenAI Responses and Ollama adapters implement the existing text-generation protocol. Network integrations have not been validated with provider credentials.

Stage 1b will establish rights-aware acquisition of non-synthetic source records, separate entity identity from source identity, and measure extraction failures on a held-out, human-annotated set. This must precede any claims about real-world extraction quality. Entity resolution and review decisions should not be delegated to the language model without verification.

## Application scope

The intended web application uses the same catalog, retrieval, and recommendation services as the notebooks and CLI. Its first flows are search, filtering, and item detail. Image search and guided recommendations follow the corresponding package implementations. The native mobile client has no assigned framework or development milestone.
