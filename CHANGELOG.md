## [0.18.0] — 2026-11-12

- Added a checksum-bound retrieval analysis plan, reviewer-sheet coverage audit and strict held-out test-evaluation gate.
- Added reproducible paired, query-level percentile bootstrap confidence intervals for BM25 versus overlap, separately for positive and no-match queries.
- Added per-query catalog-label error attribution without fabricating relevance judgments, changing ranking algorithms, or reporting real-world results from unlabeled OSM data.
- Added a local-only reviewer labeling interface (`/study-review`), Notebook 20, and an evaluation methods guide and ADR 0014.
- Preserved the frozen v0.11.0 study and existing `study evaluate` semantics.

# Changelog

## 0.17.0 — Approximate geography and reviewed local media

- Add operator-bound OSM geolocation search with deterministic Haversine ranking, source geometry classification and explicit coordinate inputs.
- Reuse the stable restaurant identity mapping used by opt-in visit suggestions; exclude unadmitted duplicate candidates.
- Add an offline, rights-review-bound local PNG publication pipeline with source and normalized hashes, EXIF stripping, attribution and modification notes.
- Expose protected read-only media endpoints and menu reference status without modifying canonical catalog or recommendation scoring.
- Integrate nearby exploration, local images, and menu-status transparency into the existing web app; add Notebook 19, tests, CLI and ADR 0013.

**Limitations:** OSM centers are not surveyed entrances; manually approved licenses are not independently verified; absence of a menu link is not proof that no menu exists. No geocoding, third-party image fetching or real-world accuracy claims.


## 0.16.0 — Opt-in restaurant visit suggestions

- Add strict, bounded, user-selected photo metadata input with timezone-aware, deterministic spatial-temporal clustering.
- Match only reviewed/admitted OSM source identities in the active catalog using wrapped-longitude Haversine distances.
- Generate private, digest-bound suggestion and review files; require explicit confirm, reject, or reassign decisions.
- Export a minimized confirmed-history artifact that omits raw coordinates, photo IDs, and review reasons.
- Add a browser-local review queue with no metadata uploads or API calls, a restrictive CSP, CLI commands, notebook 18, and regression tests.
- Keep catalog schema, search ranking, HTTP v1, MCP, media licensing, and the frozen real-data study unchanged.

**Limitations:** No camera-roll access, photo interpretation, automatically confirmed visits, or independently validated visit-matching accuracy.


## 0.15.0 — Reviewer-approved catalog references

- Introduce catalog-digest-bound evidence proposals and explicit per-claim reviews.
- Publish separate menu, image and cuisine references only after documented approval.
- Expose approved references through a read-only item evidence endpoint and web detail view.
- Keep canonical catalog, retrieval and recommendation scores unchanged.
- Document evidence limitations and borrowed review-workflow lessons from Palate.
- Correct the CI ES-module syntax check for `app.js`.


## 0.14.0 — Local-first web application

- Package a responsive, accessible browser interface served from the same FastAPI process as HTTP v1. No Node build or external CDN is required for users.
- Add restaurant/recipe browsing, server-side filters, lexical search, grounded recommendations, source/provenance links, evidence display, item details, exclusions, and pagination.
- Preserve existing `DiscoveryService` ranking and API contracts. Client data access is same-origin and bounded; HTML escapes catalog content through DOM text nodes rather than injected markup.
- Add an optional in-memory API key field, strict homepage Content Security Policy, browser and Python contract tests, Notebook 16, and a deployment guide.
- Expose the same interface through `savoroute web serve` or `savoroute api serve`; neither command opens a public network listener by default.

The UI uses saved catalog records, not verified menus, allergen safety, opening hours, pricing, or reservation availability. The existing frozen OSM relevance pilot remains unannotated. This is a local-first application milestone, not a production service launch.


## 0.13.0 — Local read-only MCP tools

- Add six read-only MCP tools for catalog metadata, item browsing, item details, search, rank fusion, and grounded recommendations.
- Target the official MCP Python SDK v2 and local stdio transport. All tool calls reuse the existing versioned FastAPI contracts through an in-process ASGI bridge, without outbound requests or a second ranking implementation.
- Keep catalog/index selection operator-controlled at startup; preserve validation, source attribution, item-level evidence, and ranking limitations.
- Add the optional `mcp` extra, protocol and bridge tests, Notebook 15, a technical guide, and ADR 0009.

The MCP server exposes no ingestion, writes, file/URL access, model downloads, or public HTTP listener. Tests on fictional catalogs do not establish real-world relevance or restaurant safety.

## 0.12.0 — Versioned read-only HTTP API

- Expose `/v1` metadata, catalog browsing, item details, search, RRF ranking, and grounded recommendations through the existing `DiscoveryService`.
- Add explicit bounded Pydantic request/response contracts, structured errors, generated OpenAPI, and optional API-key authentication.
- Load and validate an operator-selected catalog and compatible JSON/SQLite/FAISS index at application construction; no client-specified file paths or downloads.
- Add an opt-in local `savoroute api serve` command, notebook 14, contract/security regression tests, and an architecture decision record.

The development server is not production-hardened. Vector requests need an explicitly configured index and compatible encoder or trusted client-provided embedding. Real-world relevance is not established by API tests.

## 0.11.0 — Reproducible real-data study workflow

- Freeze a bounded OSM source snapshot, deterministically derived catalog, query set, and separate reviewer templates in a checksummed bundle.
- Publish reviewer-facing source references without relevance labels or retrieval scores; reject repeated normalized queries across study splits.
- Add study verification, a completion-gated lexical baseline report, CLI commands, notebook 13, and regression tests.
- Record the source license and declared selection/query protocols; preserve the existing catalog schema and review workflow.

The repository does not supply independently reviewed real-world judgments. Collection protocols, review independence, data authenticity, and external correctness cannot be verified by the package.


## 0.10.0 — Relevance review and grounded recommendations

- Add exhaustive versioned query–item review worksheets with separate reviewer sheets, explicit merge/adjudication, and catalog fingerprints.
- Export separate development/test benchmark files only after every eligible item has a valid final judgment; retain an annotation audit with agreement statistics.
- Add deterministic, catalog-grounded recommendations with hard metadata constraints, excluded items, soft preferences, retrieval ranks, and source attribution.
- Provide CLI commands, notebook 12, and regression tests; preserve schema v1 and the existing vector backends.

The repository does not contain independently reviewed real-world relevance labels. Mock notebook labels are synthetic and are not evidence of reviewer independence or real-world accuracy.

## 0.9.0 — Persistent vector retrieval

- Add immutable SQLite vector bundles with stable record IDs, manifest hashes, and float32 storage.
- Add optional FAISS HNSW indexing and approximate search with metadata mapping and filtered candidate overfetch.
- Reuse SQLite/FAISS sources in item-level RRF and add CLI build, search, and synthetic latency benchmarks.
- Add notebook 11, a 42-query fictional relevance challenge, and independent annotation guidance.

The FAISS runtime is not exercised by default CI, and the synthetic benchmarks do not establish real-world relevance or production latency.

## 0.8.0 — Item-level rank fusion

- Fuse catalog-backed BM25, text-vector, and image-vector rankings using weighted reciprocal rank fusion.
- Collapse multiple media hits to one item before candidate-pool truncation; retain per-source ranks and record IDs.
- Apply existing metadata filters across every source, with deterministic ranking and no mixed score scales.
- Add item-level evaluation using the existing relevance benchmark, CLI search/evaluation commands, and notebook 10.

RRF scores are not calibrated probabilities. The fictional benchmark and deterministic test encoder do not establish real-world retrieval quality. The JSON vector index remains intended for small catalogs.

## 0.7.0 — Joint text/image retrieval

- Add a versioned JSON vector index for catalog text and local image assets.
- Implement exact cosine search, modality filtering, item-kind filtering, and optional item deduplication.
- Validate model identity, vector dimensions, record references, and catalog fingerprints.
- Add labeled text-to-image and image-to-image evaluation and notebook 09.
- Keep CLIP inference optional and offline tests independent of model downloads.
"accept both changees "?

## 0.6.0 — Local image ingestion

- Add a versioned manifest for locally supplied images, with item references and declared source-rights metadata.
- Validate image bytes and bounded image dimensions; normalize EXIF orientation and RGB PNG output.
- Export a self-contained catalog, image assets and provenance as a new directory, with input and output hashes.
- Add an optional Sentence Transformers CLIP adapter for joint text/image embeddings, without loading models during import.
- Add notebook 08, original fictional illustration fixtures, CLI ingestion and regression tests.

Model inference, rights clearance against third-party sources, persistent embedding indexes, and live media retrieval are not verified or implemented in this release.

## 0.5.0 — OSM version ordering and identity candidate evaluation

- Record OSM element versions, timestamps, and source hashes in import reports and registry schema v2. Previous registry and import report versions remain readable.
- Reject stale source versions, inconsistent same-version content, and non-increasing edit timestamps when a version baseline exists.
- Share the candidate-review rule between OSM synchronization and annotated-pair evaluation.
- Add an unlabeled OSM annotation worksheet, a fictional benchmark, CLI commands, notebook 07, and regression tests.

No independently annotated real-world identity dataset or matching-accuracy estimate is included.

## 0.4.0 — Source identity and controlled updates

- Added a versioned source registry with explicit source-to-item bindings.
- Added controlled OSM snapshot synchronization without changing catalog schema v1 or item IDs.
- Added a review path for conflicting source records and out-of-band edits.
- Added CLI commands for registry bootstrapping, manual source links, and sync.
- Added notebook 06, an offline update fixture, and regression tests.

The matching heuristics have not been validated on independently annotated real data. Source-version ordering and transactional multi-file storage remain outstanding.

## 0.3.0 — OSM source adapter and extraction evaluation

- Added an optional bounded Overpass fetch command and deterministic OSM restaurant tag importer.
- Added candidate duplicate review, source-level import decisions, and ODbL attribution metadata.
- Added field-level exact-match extraction evaluation and notebook 05.
- Kept catalog schema v1 and existing retrieval APIs unchanged.

Live Overpass requests, actual OSM record completeness, and extraction quality on independently annotated real data have not yet been evaluated.

## 0.2.0 — Text ingestion

- Added versioned local source-batch parsing and normalized source hashes.
- Added deterministic labeled-text extraction and optional OpenAI/Ollama text-generation adapters.
- Added strict field-evidence validation with literal source spans and stable source-derived item IDs.
- Added catalog admission, provenance JSON, and CLI ingestion with overwrite protection.
- Added notebook 04 and ingestion tests. Existing catalog schema and search APIs remain unchanged.

Live model calls and extraction accuracy on real-world sources have not been evaluated.

## 0.1.0 — Retrieval foundation

- Added the version-1 fictional catalog, lexical retrieval baselines, benchmark evaluation, CLI, and notebooks 00–03.
