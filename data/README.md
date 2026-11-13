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

## Image fixtures

`image_manifest.json` references two original stylized images under `media/`. They are explicitly fictional, licensed with this repository's original code, and are not photos of restaurants or recipes. `savoroute media ingest` produces a new catalog plus PNG assets and provenance in a user-specified output directory. See [media ingestion](../docs/media-ingestion.md).

## Multimodal retrieval fixture

`multimodal_queries_fixture.json` contains two fictional text-to-image judgments and two image self-match cases. The labels are for smoke tests, not independently annotated evaluations. `savoroute vectors build` operates on the media-export catalog created by `savoroute media ingest`; the original `sample/catalog.json` has no media records. The vector index is written to a user-supplied path and is not checked into source control. See [vector index](../docs/vector-index.md).

`sample/relevance_challenge_v1.json` contains 42 curated **fictional** item-level judgments across literal, paraphrase, multi-answer, and no-match query groups. It is not independent real-world validation. See `docs/relevance-annotation.md`.

`sample/relevance_query_set_v1.json` defines fictional, unlabeled development/test queries for notebook 12 and the exhaustive annotation workflow. No reviewed real-world judgments are bundled.

Real-data study snapshots and reviewer results belong under `data/generated/` (git-ignored). The study protocol is documented in [real-data evaluation](../docs/real-data-evaluation.md). No independent human judgments are bundled.

## Milestone 3 Boston data-quality artifacts (generated, not externally verified)

The separate local development archive includes `generated/real-pilot/quality-audit-v1.json`
and `generated/real-pilot/osm-source-facts-v1.json` computed solely from the
previously saved OSM source snapshot. The source-facts file is a separate
read-only observation overlay; it is not a verified menu dataset. These
files are normally Git-ignored under `data/generated/`, so regenerate
them locally before deployment if they are absent from a Git checkout.
See `docs/data-quality-and-source-facts.md` for the exact command.
