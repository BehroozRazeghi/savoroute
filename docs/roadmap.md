# Development roadmap

The project is built in two forms at each stage: reusable library code and an executable notebook that exposes the intermediate results. CLI commands, services, and later application interfaces reuse the same implementation. A milestone is complete when its code, tests, and notebook agree.

| Stage | Scope | Acceptance criteria | Status |
| --- | --- | --- | --- |
| 0 · Foundation | Catalog parser, lexical retrieval, evaluation, CLI, four notebooks | Installable wheel; valid demo and tests; notebooks execute offline | Implemented |
| 1 · Ingestion | Source adapters, text normalization, structured extraction, field evidence | Invalid or unsupported extracted values rejected; source and transformation retained | Next |
| 2 · Multimodal data | Permitted image ingestion, media IDs, captions, text and joint embeddings | Reproducible indexes with model/metric metadata; item joins tested | Planned |
| 3 · Retrieval | Vector retrieval, deterministic filters, per-item rank fusion, benchmarks | Valid canonical IDs; measurable single-modality/fused comparisons | Planned |
| 4 · Recommendations | Preference constraints, retrieved evidence, tool calls | Grounded results, explicit failure behavior and constraint tests | Planned |
| 5 · Interfaces | HTTP API, MCP tools, responsive web client | Shared service contracts; integration, permissions and UI tests | Planned |
| 6 · Release | Reproducibility notes, deployment, end-to-end tests and demonstration | Public build and documented operating limits | Planned |

## Stage 1: ingestion

The first new notebook will be `04_structured_ingestion.ipynb`. The initial test fixture will remain local and deterministic. A concrete model adapter will be introduced alongside tests for structured output, missing attributes, unsupported values, model errors, and source evidence. IBM watsonx and at least one additional provider are candidate implementations; actual integration depends on provider access and model capability checks.

The output will be a validated source record before it is admitted to the canonical catalog. Source IDs, collection timestamps, extraction versions, and field evidence will be retained. Model outputs will not be treated as verified facts without corresponding evidence.

## Application scope

The first application is a responsive web interface backed by the same search and recommendation services used by Python clients. Its initial flows are catalog search, filters, and item details. Guided recommendations and image queries follow the underlying package implementation. The HTTP API and the web client will be introduced together with tests, rather than as empty directories.

A native mobile client has no committed framework or schedule. A mobile build will be evaluated after the web interface, based on requirements that cannot be met adequately by a responsive site or PWA.
