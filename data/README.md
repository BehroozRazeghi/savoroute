# Data

`sample/catalog.json` contains 12 fictional restaurant and recipe records. `sample/relevance_benchmark.json` contains 16 synthetic search cases. Identical fixtures are distributed in `src/savoroute/resources/` so an installed wheel can run independently of the checkout; tests check that both copies agree.

`sample/ingestion_sources.json` contains two fictional labeled source excerpts for notebook 04 and the ingestion CLI. The catalog parser validates the version-1 JSON format and verifies media-to-item references. The sample has no media attachments. The notebooks and offline tests do not download source files; the optional `savoroute osm fetch` command does.

Local inputs and generated artifacts may be placed under `data/raw/`, `data/processed/`, and `data/indexes/`. Those paths are ignored by Git. Ingestion writes validated catalog and evidence JSON to user-selected paths; the examples use ignored `data/generated/`.

[Catalog fields and provenance](../docs/data-contract.md)

`osm_overpass_fixture.json` is synthetic and has no connection to real OSM element IDs. `extraction_gold.json` contains reference fields from the fictional labeled ingestion sources. See [OSM and extraction evaluation](../docs/osm-and-extraction-evaluation.md).

- `osm_overpass_update_fixture.json`: synthetic incremental snapshot used by notebook 06 and source-sync tests.

`identity_pairs_fixture.json` contains manually assigned fictional pair labels, including expected candidate-generation failures. The `_versioned.json` OSM fixtures provide fictional element edit versions and timestamps for notebook 07 and regression tests. They are not extracts of OpenStreetMap. See [identity benchmark protocol](../docs/identity-benchmark.md).

## Image fixtures

`image_manifest.json` references two original stylized images under `media/`. They are explicitly fictional, licensed with this repository's original code, and are not photos of restaurants or recipes. `savoroute media ingest` produces a new catalog plus PNG assets and provenance in a user-specified output directory. See [media ingestion](../docs/media-ingestion.md).

## Multimodal retrieval fixture

`multimodal_queries_fixture.json` contains two fictional text-to-image judgments and two image self-match cases. The labels are for smoke tests, not independently annotated evaluations. `savoroute vectors build` operates on the media-export catalog created by `savoroute media ingest`; the original `sample/catalog.json` has no media records. The vector index is written to a user-supplied path and is not checked into source control. See [vector index](../docs/vector-index.md).
