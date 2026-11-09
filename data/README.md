# Data

`sample/catalog.json` contains 12 fictional restaurant and recipe records. `sample/relevance_benchmark.json` contains 16 synthetic search cases. Identical fixtures are distributed in `src/savoroute/resources/` so an installed wheel can run independently of the checkout; tests check that both copies agree.

The catalog parser validates the version-1 JSON format and verifies media-to-item references. The sample has no media attachments. No source files are downloaded at runtime.

Local ingestion data and generated artifacts will live under `data/raw/`, `data/processed/` and `data/indexes/` when those pipelines are implemented. Those paths are ignored by Git. The present release does not create or read them.

[Catalog fields and provenance](../docs/data-contract.md)
