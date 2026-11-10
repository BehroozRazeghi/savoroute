# Changelog

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
