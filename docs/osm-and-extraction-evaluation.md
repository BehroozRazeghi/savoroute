# OSM acquisition and extraction evaluation

This milestone adds an OpenStreetMap (OSM) restaurant source adapter and a field-level evaluation harness. Both use the existing catalog and provenance contracts. Restaurant import maps structured OSM tags directly; text extraction continues to use the separate evidence-validated extractor.

## Source acquisition

The importer reads an Overpass JSON snapshot from disk. It accepts named `amenity=restaurant` nodes, ways, and relations; only fields present in the record are mapped. A location comes from address tags or coordinates. Cuisine values are split on semicolons. Pricing, dietary tags, menus, reviews, and opening hours are not inferred. The catalog's required `description` contains the explicit adapter-generated label `Restaurant entry from OpenStreetMap.` rather than a claim about the establishment.

The optional `osm fetch` command performs one user-initiated Overpass request. Its bounding box is limited to 0.05 degrees per axis, its response to 2 MB, and its execution to 35 seconds client-side. It sends an identifying User-Agent with a contact address. It has no retry loop or scheduled refresh. Public Overpass instances have capacity constraints; check the current usage policy before making repeated requests. The live endpoint has not been exercised as part of the offline tests.

```bash
# Small-area example; replace the email with a reachable contact address.
savoroute osm fetch \
  --bbox 42.345 -71.065 42.355 -71.055 \
  --contact you@example.org \
  --output data/raw/osm_restaurants.json

savoroute osm import \
  --input data/raw/osm_restaurants.json \
  --output data/generated/osm_catalog.json \
  --report data/generated/osm_import_report.json

savoroute validate --catalog data/generated/osm_catalog.json
```

The `data/raw/` and `data/generated/` directories are excluded by `.gitignore`. For an additional snapshot, the original `osm import` path can still append new records; repeated source keys are reported as already imported. The newer `osm sync` workflow supports controlled field updates through an explicit source registry. See [source identity and updates](entity-identity-and-updates.md). Missing records are never interpreted as deletions.

## Duplicate handling

Canonical catalog IDs are reproducible hashes of the OSM element identity (`type/id`); they are not evidence of unique real-world establishments. Two elements can describe one restaurant, and a chain can have multiple locations with the same name. The importer therefore records possible duplicates instead of merging them.

A candidate is held for review when its normalized name and location match a catalog entry, or its normalized name matches an earlier imported item within 75 meters. These rules are conservative heuristics, not a resolved entity identity system. An accepted item retains the source URL in the catalog and selected source tags, geographic coordinates, and mapping decisions in the import report. `review` records are not admitted. The report must be inspected before publication or downstream use.

The packaged Overpass-format example is **entirely fictional**. It includes an explicit fixture marker and must be imported with `--synthetic-fixture`, which also prevents generated identifiers from being represented as actual OSM links.

```bash
savoroute osm import \
  --input data/sample/osm_overpass_fixture.json \
  --synthetic-fixture \
  --output data/generated/osm_demo_catalog.json \
  --report data/generated/osm_demo_report.json
```

## Extraction evaluation

The benchmark compares the values in a schema-v1 ingestion provenance report against a separately stored reference annotation file. Scalar values use normalized exact matching; array fields are treated as sets. A wrong value contributes one false positive and one false negative. Missing predicted records contribute false negatives. Unknown source IDs and duplicate annotations are errors.

\[
\mathrm{Precision} = \frac{TP}{TP+FP},\qquad
\mathrm{Recall} = \frac{TP}{TP+FN},\qquad
F_1 = \frac{2TP}{2TP+FP+FN}.
\]

Undefined ratios are represented as `null` in JSON. Micro scores pool counts across fields. `record_exact_match_rate` is the fraction of reference records for which every field matches. The evaluation does not establish semantic equivalence, annotation quality, or correctness of source claims.

```bash
savoroute ingest \
  --sources data/sample/ingestion_sources.json \
  --new-catalog \
  --output data/generated/text_catalog.json \
  --provenance data/generated/text_provenance.json

savoroute evaluate-extraction \
  --gold data/sample/extraction_gold.json \
  --predictions data/generated/text_provenance.json \
  --json
```

The included annotations were prepared from two synthetic labeled sources. They check evaluation plumbing, not the accuracy of a model on unseen documents. A genuine held-out benchmark requires independently annotated real source records and documented annotation decisions.

## Attribution and reuse

OpenStreetMap data is licensed under the Open Database License (ODbL). Public uses require attribution to OpenStreetMap contributors and relevant license notices; sharing a derived database may trigger additional ODbL conditions. Retain source links and provenance, and review those obligations before publishing any OSM-derived catalog. The repository's MIT source-code license does **not** relicense OSM data. These examples do not redistribute a live OSM dataset.

References: [OSM copyright](https://www.openstreetmap.org/copyright), [restaurant tagging](https://wiki.openstreetmap.org/wiki/Tag:amenity%3Drestaurant), [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API), [attribution guidelines](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines).

## Limitations

- The source adapter supports restaurants only; recipes remain in the text-ingestion path.
- `description` is an adapter-generated record label, not a restaurant-provided description.
- The canonical catalog does not yet store coordinates separately; coordinates remain in provenance and the source registry. Spatial search still requires additional work.
- The original importer only generates duplicate review candidates. Cross-provider source bindings and controlled OSM updates are provided by the separate registry and sync workflow.
- The offline tests mock Overpass; network reliability, data completeness, and extraction accuracy on real data remain unmeasured.
