# Reproducible restaurant relevance study

Version 0.11.0 adds a frozen, checksum-verified OSM study bundle and a command for evaluating completed, adjudicated relevance labels. The study covers only restaurants admitted from a bounded OSM snapshot. It does not claim that any unreviewed real-world relevance labels have been collected.

## Data and licensing

OpenStreetMap data is licensed under ODbL 1.0. The frozen study includes the source snapshot and the attribution `© OpenStreetMap contributors`, together with a link to https://www.openstreetmap.org/copyright. Before publishing an OSM-based database or derived database, review the ODbL requirements. The project's MIT license does not replace the data license. A restaurant's presence, classification, tags, or coordinates in OSM does not verify its opening status, menu, allergens, prices, or dietary suitability. Only explicitly sourced attributes should support judgments.

The Overpass client makes one bounded request; public instances have shared capacity and are not a general-purpose production data source. Save and reuse the original snapshot; do not repeatedly refetch during evaluation. Record the bounding box, retrieval time, and inclusion/exclusion criteria in the `selection_protocol` field. The CLI records the collection time provided by the researcher but cannot authenticate it.

## Preparing a real-data pilot

These commands illustrate the workflow. The bounding box is an example; document the actual sampling frame and choose a small area you can audit. Replace the contact address with your own before executing a network request.

```bash
savoroute osm fetch \
  --bbox 42.34 -71.10 42.36 -71.07 \
  --contact 'researcher@example.org' \
  --output data/generated/study-pilot/source.json

savoroute osm import \
  --input data/generated/study-pilot/source.json \
  --dataset osm-restaurant-pilot \
  --output data/generated/study-pilot/catalog.json \
  --report data/generated/study-pilot/import-report.json
```

Inspect the importer decisions **before** constructing queries: the imported catalog excludes rejected, incomplete, and review-queue records. This exclusion is part of the sampling design, not ground truth about the restaurants. Review possible duplicate candidates separately and record how unresolved cases affect inclusion. Do not rely on OSM alone for menu-level or allergen claims.

Create `data/generated/study-pilot/queries.json` before running or inspecting ranking results. The query-set structure is:

```json
{
  "query_set_version": 1,
  "queries": [
    {"case_id": "dev-01", "query": "restaurants serving noodles", "filters": {"kind": "restaurant"}, "split": "development"},
    {"case_id": "test-01", "query": "places with Italian cuisine", "filters": {"kind": "restaurant"}, "split": "test"}
  ]
}
```

These are **query-format examples**, not judgments or evidence that the source snapshot contains relevant restaurants. Derive real queries from an independently documented collection protocol. Include plausible matches, ambiguous descriptions, and cases with no relevant catalog item. The package detects identical queries after case/punctuation normalization, but cannot detect semantically similar paraphrases crossing the development/test boundary; review these manually. Use only filters supported by observed metadata (OSM-derived records do not contain verified dietary labels or prices).

Freeze the source, derived catalog, query set, original reviewer worksheets, and reviewer-facing item reference into a new directory:

```bash
savoroute study prepare-osm \
  --source data/generated/study-pilot/source.json \
  --catalog data/generated/study-pilot/catalog.json \
  --queries data/generated/study-pilot/queries.json \
  --output-dir data/generated/study-pilot/frozen \
  --collected-at '2026-11-12T12:00:00Z' \
  --selection-protocol 'Describe bbox, collection, and inclusion criteria' \
  --query-protocol 'Describe independent query sampling and split assignment'

savoroute study verify --study-dir data/generated/study-pilot/frozen
```

Use the **actual** timestamp and protocols, not these placeholders. The study directory cannot overwrite a prior bundle. The manifest records input hashes, catalog fingerprint, record counts, review coverage, source-admission decisions, and ODbL attribution. `verify` checks file hashes and reconstructs the catalog and review template. Checksums detect accidental changes but are not signed evidence of independent human annotation or source authenticity.

## Independent labeling and final evaluation

Reviewers receive separate blank files (`reviewer_a.json` and `reviewer_b.json`) and the unlabeled `review_reference.json` with query text, item attributes, and source links. They must not see each other's decisions or retrieval rankings. Positive labels require a rationale. Human reviewers should explicitly distinguish *not established by available source evidence* from a proven negative; the current binary protocol is suitable only if the task's annotation policy defines the interpretation of `false` in advance. If evidence is insufficient or disagreement cannot be resolved, stop rather than manufacturing labels.

The frozen files are **templates**: copy them to a separate review workspace before editing. After review, merge with the existing workflow:

```bash
savoroute judgments merge \
  --catalog data/generated/study-pilot/frozen/catalog.json \
  --workbook data/generated/study-pilot/frozen/review_template.json \
  --reviewer-a data/generated/study-pilot/reviews/reviewer_a.json \
  --reviewer-b data/generated/study-pilot/reviews/reviewer_b.json \
  --output data/generated/study-pilot/reviews/adjudicated.json
```

Disagreements require a final decision and explanation in the merged workbook. The study evaluator independently calls the strict finalizer; it refuses incomplete or contradictory judgments.

```bash
savoroute study evaluate \
  --study-dir data/generated/study-pilot/frozen \
  --workbook data/generated/study-pilot/reviews/adjudicated.json \
  --split development --at-k 5 \
  --output data/generated/study-pilot/development-report.json
```

Freeze the ranking methods and parameters before a **single designated test evaluation**:

```bash
savoroute study evaluate \
  --study-dir data/generated/study-pilot/frozen \
  --workbook data/generated/study-pilot/reviews/adjudicated.json \
  --split test --allow-test --at-k 5 \
  --output data/generated/study-pilot/test-report.json
```

The v0.11.0 study report compares two fixed lexical baselines (BM25 and weighted overlap). It reports per-query output IDs, Recall@k, reciprocal rank, nDCG, and correct-empty behavior separately. No rank-fusion or model inference is performed in this command. The report includes the study manifest hash, catalog fingerprint, adjudicated-workbook hash, and annotation audit. Its metrics measure relevance **only according to the supplied judgments**. The software does not check reviewers' identities, honest independence, authenticity of collection timestamps, factual truth of restaurant tags, or whether test queries influenced development.

For a credible public experiment, publish the written annotation policy, query sampling rationale, source date and license, catalog inclusion/exclusion counts, labeled sample sizes, agreement statistics, error analysis, model/index revisions (if used), and any exclusions. Do not publish human reviewer identity or third-party data beyond the rights granted by the source license. Empty-query correctness is not interchangeable with positive-query Recall@k.

## Scope and remaining work

The two local OSM fixtures and notebook 13 are **synthetic demonstrations** and must not be reported as real-data results. Real source acquisition, independent judgments, reviewer recruitment, and verification of external facts require human work outside the package. The current exhaustive two-reviewer protocol is bounded by `--max-pairs` and is not designed for web-scale relevance pools. Larger catalogs need a separately justified sampling and missing-judgment policy. Future multimodal studies also require rights-cleared real images and a frozen joint-embedding model; OSM restaurant tags alone do not provide that evidence.

## Evaluation methodology note

This small-catalog protocol uses exhaustive judgments over all items admitted by each query's hard filters. Large-scale test collections often use pooled judgments instead, with unjudged items treated according to an explicitly defined policy. Such pooled judgments are not interchangeable with this exhaustive protocol, and naively treating unjudged items as negatives can bias measured results. See the [NIST TREC 2021 overview](https://trec.nist.gov/pubs/trec30/papers/Overview-2021.pdf) for a discussion of pooling and incompleteness.


## v0.18.0 analysis and reviewer interface

See [Statistical relevance study](statistical-relevance-study.md) for the new local labeling page, checksum-bound analysis plan, blind-safe reviewer-progress audit, paired query-bootstrap uncertainty estimates, error analysis and strict test-split release. The existing frozen v0.11.0 study and `study evaluate` command remain compatible. No independent labels or real-world scores are supplied by this release.
