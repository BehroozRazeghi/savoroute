# Roadmap

This is a forward-looking quality plan, not a release diary. Completed milestones are recorded in [CHANGELOG.md](../CHANGELOG.md). The current implementation is summarized in the [architecture](architecture.md).

## Next work, in order

| Priority | Work | Completion criterion |
| --- | --- | --- |
| P0 | Product and documentation consistency | One accurate project objective; README and linked guides match implemented interfaces and known limitations |
| P1 | Discovery UI redesign | Search-first layout; usable on narrow screens and keyboard; clear dataset identity, loading/empty/error states, and source details; tested against fictional and saved OSM catalogs |
| P1 | Interaction and accessibility verification | Defined user tasks, accessibility review, browser regressions, and documented defects; no untested claims of WCAG conformance |
| P1 | Data completeness and product boundaries | Missing-field coverage reported; unknown attributes never displayed as asserted facts; external media only after rights review |
| P1 | Execute Boston reviewer pilot | Frozen protocol, two independent reviewers, completed or explicitly unresolved labels, adjudication, and an appropriately limited report |
| P2 | Broader independent relevance benchmark | Diverse, documented query sampling and geographic coverage; test sets fixed before method tuning |
| P2 | Retrieval changes supported by evaluation | Error-driven changes with ablation and paired comparisons; no assumed improvement from adding models |
| P3 | Deployment assessment | Authentication, network exposure, rate limits, observability, data retention, privacy, licenses, and load testing before hosting beyond loopback |

See the [product-quality plan](product-quality-plan.md) for the precise work sequence and acceptance tests.

## Current scope

Implemented locally: JSON catalog validation, OSM ingestion and source identity management, lexical search, optional vector retrieval and rank fusion, preference-based recommendations, HTTP API, local MCP tools, web discovery, geographic lookup, review-bound media, private visit suggestions, and human relevance-study tooling.

Not established: independent real-world retrieval effectiveness, verified venue/menu freshness, allergen safety, public deployment readiness, or consumer usability. The bundled catalogs and notebook benchmarks are fictional.

## Completed ingestion work

Stage 1a reads a bounded local source batch, extracts supported catalog fields, attaches exact text quotations, and checks that each extracted value occurs within its quoted source span. It derives a stable item ID from the source ID, checks admission against catalog schema v1, and writes canonical catalog and provenance JSON files. OpenAI Responses and Ollama adapters implement the existing text-generation protocol. Network integrations have not been validated with provider credentials.

Stage 1b provides a bounded Overpass client, an OSM JSON importer, and a review queue for possible duplicate establishments. Catalog IDs are currently source-derived, so they are not yet independent entity identities. Field-level evaluation compares text-extraction provenance against reference labels. The included synthetic labels do not measure out-of-sample extraction quality.

Stage 1c keeps catalog schema v1 and records source identities in a separate registry. An exact source key can update its source-owned item; possible duplicates require review, and other-provider links are explicitly recorded without merging fields. The system keeps existing item IDs and media associations. Source removal is not inferred from bounded snapshots. See [entity identities and updates](entity-identity-and-updates.md).

Stage 1d adds OSM metadata-aware reconciliation and pairwise evaluation of the same blocking rule used in synchronization. The worksheet generator prepares bounded OSM snapshots for manual labeling; it does not assign truth labels. The included annotated sample is fictional. An independently annotated real benchmark, sampling design, inter-annotator agreement, and licensing review are still outstanding. See [identity candidate evaluation](identity-benchmark.md).

## Application scope

The implemented local-first web interface reuses the same catalog, retrieval, and recommendation services as the notebooks and CLI. It supports search, filtering, evidence-aware details, and result comparison. The native mobile client has no selected framework or planned implementation milestone.

## Local image processing

Stage 2a validates explicit local file references and exports normalized RGB PNG assets with source and output SHA-256 hashes. Output `catalog.json` uses relative asset URIs and retains catalog schema v1. `provenance.json` records declared source rights; it does not verify permissions. The current command exports a new directory from a catalog without pre-existing media. Image discovery and external fetching are separate concerns. See [image ingestion](media-ingestion.md).

## v0.13.0 — Local MCP adapter (implemented)

Six read-only, stdio-only MCP tools reuse HTTP v1's in-process services,
validation, error handling, provenance, and preference constraints. Remote
MCP/Streamable HTTP deployment is not part of this milestone. See
[local MCP design](mcp-server.md) and [ADR 0009](adr/0009-local-mcp-adapter.md).

Next: a grounded user-facing agent workflow (not currently implemented), deployment/security design,
and independently reviewed real-world relevance measurements.

## Milestone 4 — Local-first web app (v0.14.0)

- Ship a browser application bundled in the Python wheel, sharing the existing HTTP v1 read-only API.
- Include interactive query/filter controls, recommendation preferences, result evidence, provenance, catalog paging and item details, responsive layout and accessibility measures.
- Preserve the already validated local stdio MCP boundary and versioned HTTP contracts.
- Keep real-world annotation, deployed authentication, rate limits and live availability outside the scope of this release.

Next: evaluate the OSM study with independent human labels, harden deployment only after product needs are clear, and expand the UI with validated data such as genuine photos or menus subject to rights and provenance.


### v0.15.0 — evidence-first catalog references

Approved menu links and image URLs carry source, observation date, attribution and manual review details in a separate catalog-bound sidecar. No camera-roll permissions or automatic photo downloads. Possible later increments: license-aware first-party media packaging, curated catalog coverage, and a separately consented local photo/visit suggestion queue inspired by Palate's human confirmation pattern.


### v0.18.0 — Reproducible real-data relevance evaluation (software)

Implemented: local independent reviewer worksheet interface, incomplete-label progress audit, frozen analysis configuration, strict held-out release, fixed BM25/overlap baselines, paired query bootstrap and error reports. The actual 165-record Boston OSM pilot remains **unlabeled** until independent reviewers complete and adjudicate its 1,320 query–item pairs. Future work: rigorous labeling and reporting, larger geographically diverse query sets, and validation of multimodal systems with frozen model/index configurations.


### v0.19.0 — Search-first product UX and pinned Boston boundary workflow

Implemented responsive search-first discovery, mode chips, hidden advanced filters, source-grounded result comparison and browser interaction regression tests. Added official Boston GIS import validation and documented audit gates, but actual polygon acquisition and adjudication of 41 missing city tags remain pending because the boundary could not be fetched in the release environment.


### v0.20.0 — Reproducible source-quality audit and opt-in source observations

Implemented offline field coverage, review queue, and catalog-bound raw OSM
source observations, visible in the item detail panel with explicit uncertainty.
Source facts do not modify catalog indexing, filters, or recommendations. The
Boston snapshot has no real recipes, no price tiers, and no informative restaurant
descriptions. The 41 city-unattributed restaurants remain unresolved. Next:
independent geographic backfill and lawful, human-reviewed restaurant and
recipe sourcing; see `docs/data-quality-and-source-facts.md`.

### v0.21.0 — Small attributed recipe seed, not recipe-market coverage

A strict offline import now exercises 3 real-source, revision-linked Wikibooks Cookbook recipe adaptations beside the unchanged 165 OSM restaurants, with an authorized web/API preparation panel and separate CC BY-SA content obligations. These recipes remain unreviewed for culinary correctness and dietary/allergen safety. An explicit 41-record Boston municipality queue makes the official polygon dependency auditable; no additional cities were inferred. Next gates: independent source review, legally usable menu/photo content, actual municipal boundary retrieval, diverse real recipes, and benchmark relevance judgments. Full policy and commands: `docs/recipe-curation-m4.md`.
