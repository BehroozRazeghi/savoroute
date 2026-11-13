# Frozen relevance study: annotation, uncertainty, and diagnostics (v0.18.0)

**State of evidence:** This release provides reproducible evaluation *software*, not measured real-world retrieval performance. The existing Boston pilot has eight researcher-written queries and 165 admitted OSM restaurants (1,320 query–item pairs) but no independently collected, adjudicated judgments in this repository. Do not quote fictional notebook results as real-world effectiveness.

## Scope and estimand

The unit of analysis is a **query**, and the measured target is effectiveness on the **fixed, filtered, admitted OSM catalog**, not coverage of all restaurants, verified menus, open businesses, or user satisfaction. The frozen study currently evaluates **binary relevance**, with lexical BM25 and overlap baselines as implemented by Savoroute. This milestone does **not** benchmark learned embeddings, geographic matching, images, agent quality, or real restaurant visit accuracy.

The study bundle from `savoroute study prepare-osm` must be created **before** model selection, inspecting rankings, or annotating labels. `savoroute study verify` checks the snapshot, catalog, query set, hashes, pair coverage, and blank review templates. Source integrity checks cannot authenticate the actual date, reviewer identity, independence, or correctness of human labels.

### Annotation policy to specify before reviewers begin

1. Document who writes the queries, how they are sampled, the intended relevance definition, and the geographic and time coverage. Define `true` and `false` using *available source evidence*. An unlisted cuisine or menu is **unknown**, not evidence of a negative claim about the business. If the binary decision is not defensible, do not force a label: revise the study protocol *before* annotation or leave the review incomplete and explain the limitation.
2. Provide two people separate copies of `reviewer_a.json` and `reviewer_b.json`, plus the shared **unlabeled** `review_reference.json`. Show neither reviewer another's answers or any retrieval scores/positions until they submit independently. A single person editing both sheets does **not** constitute independent annotation.
3. In each sheet set `relevant` to `true` or `false`. A positive requires a **specific rationale** in `note`; negative notes can describe evidence limitations. Every eligible pair must be decided in both sheets; incomplete reviews cannot become a benchmark.
4. Adjudicate disagreements manually in the `judgments merge` output. Supply `final_label` and `adjudication_note` for every disagreement, including the source/evidence basis. Do not override agreed labels silently. The package refuses incomplete or contradictory adjudication. Record evaluator conflicts of interest and unresolved ambiguities outside the software.
5. Preserve original completed reviewer sheets, adjudicated workbook, and analysis outputs in private, access-controlled storage. Do not add names, personal visits, private photo metadata, or raw human notes to Git. Keep the OSM attribution and comply with ODbL when distributing derived data.

## Labeling UI (optional, local-only)

Start the existing local web server:

```bash
savoroute web serve --host 127.0.0.1 --port 8001
```

Open `http://127.0.0.1:8001/study-review`. Select only `review_reference.json` and **your** copy of `reviewer_a.json` **or** `reviewer_b.json`. Review pair by pair, using **Next unreviewed** to revisit incomplete cases. Download your reviewer-specific JSON periodically and after completing the sheet. The browser does not fetch ratings, relevance predictions, or the other reviewer's sheet, and neither file is sent to Savoroute's server. This is not a substitute for the Python-side study integrity checks.

## Command-line workflow

Use your actual frozen directory path (below: `data/generated/real-pilot/frozen`). The existing real-data snapshots, reviewer files, and reports belong under `data/generated/` and remain ignored by Git.

```bash
savoroute study verify --study-dir data/generated/real-pilot/frozen

# Create the *analysis plan first*. It fixes the two baselines, primary metric,
# k, reproducible seed, and bootstrap configuration; no overwriting allowed.
savoroute study plan \
  --study-dir data/generated/real-pilot/frozen \
  --primary-metric ndcg_at_k --at-k 5 \
  --resamples 2000 --seed 2026 \
  --output data/generated/real-pilot/analysis-plan.json

# Inspect individual sheet completion WITHOUT exporting either person's labels.
savoroute study audit \
  --study-dir data/generated/real-pilot/frozen \
  --reviewer-a data/generated/real-pilot/reviews/reviewer_a.json \
  --reviewer-b data/generated/real-pilot/reviews/reviewer_b.json \
  --output data/generated/real-pilot/review-audit.json

# After BOTH independent sheets are complete:
savoroute judgments merge \
  --catalog data/generated/real-pilot/frozen/catalog.json \
  --workbook data/generated/real-pilot/frozen/review_template.json \
  --reviewer-a data/generated/real-pilot/reviews/reviewer_a.json \
  --reviewer-b data/generated/real-pilot/reviews/reviewer_b.json \
  --output data/generated/real-pilot/reviews/adjudicated.json

# Manually resolve *all* disagreements in adjudicated.json, then:
savoroute study analyze \
  --study-dir data/generated/real-pilot/frozen \
  --workbook data/generated/real-pilot/reviews/adjudicated.json \
  --plan data/generated/real-pilot/analysis-plan.json \
  --split development \
  --output data/generated/real-pilot/development-analysis.json

# Designate ONE held-out test run after all choices are frozen.
savoroute study analyze \
  --study-dir data/generated/real-pilot/frozen \
  --workbook data/generated/real-pilot/reviews/adjudicated.json \
  --plan data/generated/real-pilot/analysis-plan.json \
  --split test --allow-test \
  --output data/generated/real-pilot/test-analysis.json
```

The `--allow-test` gate is a safeguard against accidental evaluation, **not** a technical guarantee against repeated peeking at test outcomes. To claim preregistration, externally timestamp/sign and register your plan before test access; the JSON is merely checksum-bound. The audit reports completion counts and aggregate disagreements, not review labels.

## Metrics and statistical methods

For positive-relevance queries the software reports macro **Recall@k**, **MRR@k** (reciprocal rank of first relevant item) and binary **nDCG@k**. For zero-relevant-item queries it reports **correct-empty-output rate** separately; a no-match query is not assigned a fictitious zero Recall/MRR/nDCG. Each query contributes equally within its own stratum. The old `study evaluate` command remains available and unchanged.

`study analyze` adds the following for each metric:

- Mean effectiveness for each fixed baseline and the **paired difference `BM25 − overlap`**, computed for **identical query IDs**.
- Deterministic **95% percentile bootstrap intervals** resampling **whole queries with replacement**, never query–item pairs. Positive and zero-match strata are resampled **separately**. The number of resamples, seed, and primary metric are frozen in the plan. The same sampled query indices are applied to both baselines for paired differences.
- No interval with fewer than **two queries** in a stratum; undefined metrics have null estimates. Small-n percentile intervals can be unstable and do not include judgment uncertainty.
- Per-query retrieved IDs and error sets (retrieved judged-irrelevant IDs; unretrieved relevant IDs), plus counts of `zero_recall`, `partial_recall`, `no_results_for_positive_query`, `false_positive_on_no_match`, etc. These are **catalog-label-based diagnostics**, not independently verified facts about real businesses.

These are **descriptive/exploratory estimates**, not a preregistered null-hypothesis test. With four development and four test queries, intervals are highly sample-sensitive and should **not** be used to claim superiority or generalization. Report the number of *positive* and *no-match* queries with every metric. Do not treat per-restaurant pairs as independent observations. The independent labels themselves can be uncertain even when reviewers agree.

## What to report in a manuscript

A rigorous empirical report should disclose at least: bounded geographic and temporal sampling frame; OSM acquisition date/license; catalog admission/rejection counts; query collection protocol; development/test separation; reviewer independence procedure and conflicts; judgment completeness; positive-label prevalence; observed agreement and Cohen's kappa (including prevalence caveats); adjudication procedure; primary metric and k; per-stratum query counts; BM25/overlap definitions; point estimates and paired bootstrap intervals; individual failure cases and missing metadata limitations; all instances of model or parameter tuning; and whether the held-out test was consulted more than once.

### Explicit limitations

- No score can establish food safety, dietary or allergen compatibility, image rights, business opening status, menu actuality, or user visit history.
- With exhaustive labels **within** the small filtered catalog, Recall@k has a precise finite-set denominator, but this says nothing about restaurants excluded by the OSM importer or absent from OSM.
- Query-level bootstrap CIs estimate variation over the given query-sampling process *if* the sample is representative. Hand-written convenience queries do not automatically constitute a random sample.
- Agreement statistics calculated across 1,320 correlated query–item pairs are descriptive; they are not 1,320 independent experimental units.
- The current evaluation treats each relevance judgment as binary. If source evidence routinely permits only ambiguous judgments, redesign and re-freeze the annotation study rather than inventing negative labels.

## Method references

- NIST TREC relevance judgments and evaluation collection guidance: https://trec.nist.gov/data/reljudge_eng.html
- I. Soboroff, *Computing confidence intervals for common IR measures*, EVIA 2014: https://www.nist.gov/publications/computing-confidence-intervals-common-ir-measures
- M. D. Smucker, J. Allan, B. Carterette, *A Comparison of Statistical Significance Tests for Information Retrieval Evaluation*, CIKM 2007: https://ciir-publications.cs.umass.edu/pub/web/getpdf.php?id=744
