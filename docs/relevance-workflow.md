# Relevance annotation and evaluation

Savoroute uses a separate annotation workbook to collect binary query–item judgments. No component generates relevance labels automatically. The workbook contains both reviewer slots, an explicit final decision, the catalog fingerprint, and separate development and test query partitions. Export requires completed reviews for every eligible query–item pair.

For a source-bound OpenStreetMap pilot, [freeze the source snapshot and query set](real-data-evaluation.md) before distributing reviewer sheets. The exported test split evaluates held-out queries on the same catalog, not unseen restaurants.

## Workflow

1. Freeze a rights-cleared catalog snapshot and document its data sources, collection time, scope, missing fields, and source-license requirements. The catalog `synthetic` flag is descriptive metadata, not evidence of accuracy or annotation provenance.
2. Write a version-1 query set with distinct query IDs, nonempty queries, hard filters, and a predetermined `development` or `test` split. Query construction and sampling should be independent of the results being evaluated. The included query set is fictional and illustrative.
3. Run `savoroute judgments prepare`. The output covers every catalog item admitted by each query's hard filters. A bounded exhaustive design prevents treating unjudged retrieved items as nonrelevant; generation refuses more than `--max-pairs` pairs. This workflow is intended for small catalogs, not web-scale corpora.
4. Run `savoroute judgments split` to generate two **separate blank reviewer files**, cryptographically tied to the same workbook template. Give each reviewer only their own file and the frozen catalog/source material. Reviewers set `relevant` to a JSON boolean, explain positive decisions in `note`, and should not inspect model ranks or the other reviewer's file. Reviewers need not share identifying information with the package.
5. Run `savoroute judgments merge`. The merge rejects incomplete responses, wrong reviewer slots, duplicate or missing query–item pairs, and mismatched template fingerprints. Agreements receive an automatic `final_label`; disagreement labels remain `null` until an adjudicator records a final decision and a nonempty `adjudication_note`. Reviewer decisions are retained unchanged.
6. Run `savoroute judgments finalize` on the merged/adjudicated workbook. The command rejects unresolved disagreements, catalog changes, and contradictory agreement decisions. Successful export produces `development.json`, `test.json`, and `audit.json`. The audit records the workbook SHA-256, catalog SHA-256, observed agreement, Cohen's kappa when defined, and disagreements. Separate files support blinded review but cannot authenticate reviewer independence.
7. Develop retrieval and preference policies with the development split only. Freeze the implementation and parameters before evaluating the test split. Report Recall@k, MRR@k, nDCG@k, no-result behavior, sample sizes, and query strata where available. Do not optimize on the test split or mistake observed agreement for objective relevance accuracy.

```bash
savoroute judgments prepare \
  --catalog data/sample/catalog.json \
  --queries data/sample/relevance_query_set_v1.json \
  --output data/generated/relevance_workbook.json

savoroute judgments split \
  --catalog data/sample/catalog.json \
  --workbook data/generated/relevance_workbook.json \
  --output-dir data/generated/reviewers

# Give each reviewer only their own JSON file. After both submit:
savoroute judgments merge \
  --catalog data/sample/catalog.json \
  --workbook data/generated/relevance_workbook.json \
  --reviewer-a data/generated/reviewers/reviewer_a.json \
  --reviewer-b data/generated/reviewers/reviewer_b.json \
  --output data/generated/adjudication.json

# Resolve disagreements in adjudication.json, then export:
savoroute judgments finalize \
  --catalog data/sample/catalog.json \
  --workbook data/generated/adjudication.json \
  --output-dir data/generated/approved_qrels

savoroute rank evaluate \
  --catalog data/sample/catalog.json \
  --benchmark data/generated/approved_qrels/test.json \
  --at-k 5 --json
```

The generated benchmarks use the existing binary `benchmark_version=1` format. The audit is a required companion artifact for interpreting their provenance; the exported benchmark alone does not encode the annotation protocol. The three output files are written atomically **individually**, not as a multi-file transaction.

## Limitations

- The default catalog and query set are synthetic; they do not provide independent real-data evaluation. Real annotations must be gathered and adjudicated separately.
- Exhaustively judging each filtered catalog item scales as the product of query count and eligible item count; use a separate documented pooling and missing-judgment policy for larger corpora. Do not treat unjudged candidates as negatives.
- The code cannot verify that the reviewers are different people, that evidence notes are correct, or that queries are representative. Annotation provenance and sampling require external process controls.
- Hard filters exclude items with unknown required metadata. An empty result means no matching *catalog* item, not that no such food or restaurant exists.
- RRF and cosine similarities are ranking values, not calibrated probabilities. No-match performance is measured only on known, labeled tasks.
- Any real-world restaurant metadata may be stale; source rights and OSM attribution must be maintained separately.
