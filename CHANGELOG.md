# Changelog

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
