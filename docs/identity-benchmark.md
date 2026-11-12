# Identity candidate benchmark

Savoroute proposes records for human identity review; it does not infer an entity link from a matching name or distance alone. The current candidate rule requires equal normalized names and either an equal normalized address or coordinates within 75 m. The same function is used by OSM synchronization and this evaluation module.

## Annotation format

`data/sample/identity_pairs_fixture.json` is an annotated, **fictional** example. Schema v1 requires a dataset name, an explicit `synthetic` boolean, annotation provenance, named records with optional coordinate pairs, and unique unordered pairs labeled with a boolean `same_entity`. Missing labels are errors, not negative examples. IDs must refer to records in the same file.

The evaluation reports TP, FP, FN, TN, pairwise precision and recall, F1, and candidate-review rate. Undefined precision or recall is returned as `null`. Reported false-positive and false-negative pair IDs allow inspection. Metrics are computed **only on supplied annotated pairs**; they do not measure recall over unseen pairs or performance on all businesses.

```bash
savoroute identity evaluate --benchmark data/sample/identity_pairs_fixture.json --json
```

The fictional fixture deliberately contains two businesses with identical names and addresses, and a true match with a name variant. These examples expose limitations of the exact-name blocking rule; their metrics are not evidence of real-world quality.

## Preparing a real-data review

Fetch and save a **bounded** OSM Overpass snapshot using the existing `savoroute osm fetch` command, or use an existing permitted local snapshot. In the local checkout:

```bash
savoroute identity prepare-osm \
  --input data/raw/restaurants.json \
  --output data/processed/identity-review.json \
  --max-records 80 --max-pairs 200
```

The output is a worksheet, not gold labels: all `same_entity` fields are `null`. An independent reviewer must assign `true` or `false` based on evidence, not the candidate rule, before the evaluator accepts the file. Keep uncertain cases out of a finalized benchmark and document exclusions. The template places candidate pairs before noncandidate controls; its selection is deterministic and **not prevalence-representative**. Measure performance for this reviewed sample only. For claims about deployment performance, construct an independently sampled, stratified evaluation set with appropriate weighting and report its sampling design.

Maintain source references, labeling rules, review date, disagreement resolution, and licensing/attribution documentation separately. Real OpenStreetMap data is subject to ODbL terms and OpenStreetMap attribution requirements. Do not commit raw downloaded source data or a derived dataset before rights and redistribution conditions have been reviewed.

The repository does not include independently annotated real-world matches, and no such accuracy result is claimed.
