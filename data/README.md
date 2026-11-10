# Data

`sample/catalog.json` contains 12 fictional restaurant and recipe records. `sample/relevance_benchmark.json` contains 16 synthetic search cases. Identical fixtures are distributed in `src/savoroute/resources/` so an installed wheel can run independently of the checkout; tests check that both copies agree.

`sample/ingestion_sources.json` contains two fictional labeled source excerpts for notebook 04 and the ingestion CLI. The catalog parser validates the version-1 JSON format and verifies media-to-item references. The sample has no media attachments. The notebooks and offline tests do not download source files; the optional `savoroute osm fetch` command does.

Local ingestion data and generated artifacts will live under `data/raw/`, `data/processed/` and `data/indexes/` when those pipelines are implemented. Those paths are ignored by Git. Ingestion writes validated catalog and evidence JSON to user-selected paths; the examples use ignored `data/generated/`.

[Catalog fields and provenance](../docs/data-contract.md)

`osm_overpass_fixture.json` is synthetic and has no connection to real OSM element IDs. `extraction_gold.json` contains reference fields from the fictional labeled ingestion sources. See [OSM and extraction evaluation](../docs/osm-and-extraction-evaluation.md).

- `osm_overpass_update_fixture.json`: synthetic incremental snapshot used by notebook 06 and source-sync tests.
