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
