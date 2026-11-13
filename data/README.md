# Data and fixtures

The files in `data/sample/` are **fictional test and tutorial inputs**. They are not a current restaurant directory and must not be used to claim real-world retrieval quality. Package copies under `src/savoroute/resources/` support installed examples; tests check fixture consistency.

| Group | Purpose |
| --- | --- |
| `catalog.json`, `relevance_benchmark.json` | Twelve fictional restaurants/recipes and a small synthetic search benchmark |
| `relevance_challenge_v1.json`, `relevance_query_set_v1.json` | Fictional retrieval cases and blank reviewer-query setup |
| `ingestion_sources.json`, `extraction_gold.json` | Source extraction and evidence checks |
| `osm_overpass*.json`, `identity_pairs_fixture.json` | Fictional OSM-format imports, updates, and identity evaluation |
| `image_manifest.json`, `media/` | Local original illustrative image fixtures and declared rights metadata |
| `multimodal_queries_fixture.json` | Synthetic text-to-image and image-match checks |
| `evidence_candidates_demo.json`, `visit_photo_metadata_fixture.json` | Fictional reviewed-evidence and opt-in visit workflow demonstrations |

Saved OSM extracts, external data, vector indexes, image outputs, personal metadata, and reviewer workbooks should remain under ignored paths such as `data/generated/`, `data/raw/`, or `data/indexes/`. Do not commit credentials, private annotations, or original third-party assets without appropriate rights.

An imported OSM record may have no verified cuisine, pricing, menu, or business status. Missing fields are unknown, not negative facts. Source attributions and catalog fingerprints support traceability, not factual verification.

See [catalog contract](../docs/data-contract.md), [ingestion](../docs/osm-and-extraction-evaluation.md), [reviewed evidence](../docs/reviewed-evidence.md), and [evaluation methodology](../docs/statistical-relevance-study.md).
