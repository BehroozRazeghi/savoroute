# Savoroute Boston OSM relevance pilot — execution protocol

**Scope:** Run the **already frozen** eight-query, 165-restaurant Boston OSM pilot
using the v0.18.0 reviewer and evaluation software. This is a *human-judgment
study*, not a new Savoroute product release. The local study directory under
`data/generated/` is not included in the public Git repository or in this kit.

**Do not publish real-world quality measurements until two separate human reviewers
have independently completed every eligible pair, their disagreements have been
adjudicated, and the analysis has been run from a frozen, validated plan.**
The 1,320 pair judgments do *not* correspond to 1,320 independent evaluation
units: the experiment has eight queries, four per partition.

## 1. Confirm exactly which collection you have

```bash
conda activate savoroute
cd ~/my_github/savoroute
# Find the frozen study once: only use the path that contains manifest.json.
find data/generated/real-pilot -name manifest.json -print
```

Set the actual directory. Here we assume `data/generated/real-pilot/frozen`:

```bash
export STUDY=data/generated/real-pilot/frozen
export PILOT=data/generated/real-pilot/study-operations
savoroute study verify --study-dir "$STUDY"
python scripts/study_pilot.py preflight --study-dir "$STUDY"
```

The preflight lists pairs and the proportion lacking recorded cuisine for each
query. **Missing cuisine is unknown evidence, never proof of nonrelevance.** If
the source does not support the binary judgment, do not assign `false` to make
the workbook complete. Log the limitation and halt the study for protocol
revision and re-freezing. Even independent agreement cannot repair an invalid
label definition.

If the frozen study does not exist, do not invent its contents. Reconstruct it
from the original saved Overpass `source.json`, matching imported `catalog.json`,
and original query set with `savoroute study prepare-osm`, preserving acquisition
metadata and documenting why it was re-created. A reconstructed snapshot is a
**new** study and must not be represented as an unchanged prior freeze.

## 2. Record the protocol *before* the reviewers begin

The coordinator must record, outside the software, all of the following:

- Precise **estimand**: Does the frozen catalog record contain sufficient
  evidence that the establishment satisfies the written food/cuisine query?
  This is *not* a claim about current menus, operation, service, or suitability.
- Inclusion/exclusion rules: define the interpretation of each query (e.g.,
  cuisine aliases, mixed cuisines, venues with multiple activities) and what
  constitutes a defensible binary positive/negative from a frozen source.
- Evidence hierarchy: frozen OSM tags and descriptions first; if additional
  evidence is permitted, specify sources, snapshot dates, and archiving rules
  *before* judging. Avoid live-web changes to historical ground truth.
- Unknown/ambiguous cases: retain `null` and report to coordinator. v0.18
  intentionally forbids a complete benchmark with unresolved labels; do **not**
  use `false` to impute unknowns.
- Exactly two independent reviewers, no mutual sharing of answers, query/model
  rankings, or adjudication prior to completing both sheets. Separately record
  reviewer conflicts and any query-author involvement.
- Fixed split, primary metric nDCG@5 for positive queries, paired BM25–overlap
  comparison, 2,000 query-level resamples, seed 2026. Treat estimates as
  descriptive; no statistical significance claim with this convenience sample.
- Test access policy: do not run held-out evaluation until human decisions,
  adjudication, analysis choices, and diagnostic categories are frozen.

Complete the provided [`study-protocol-template.md`](study-protocol-template.md)
*before* distributing reviewer files. Sign or independently timestamp the
completed plan to support a genuine preregistration claim; `study plan` alone
is not independently time-stamped.

```bash
mkdir -p "$PILOT"
savoroute study plan \
  --study-dir "$STUDY" \
  --primary-metric ndcg_at_k --at-k 5 --resamples 2000 --seed 2026 \
  --output "$PILOT/analysis-plan.json"
```

If the plan already exists, **use it** rather than overwriting or silently
changing the configuration. Any post-hoc change must be disclosed.

## 3. Create blinded reviewer packages

```bash
python scripts/study_pilot.py package-reviewers \
  --study-dir "$STUDY" \
  --plan "$PILOT/analysis-plan.json" \
  --output-dir "$PILOT/reviewer-packages"
```

This writes `reviewer_a.zip`, `reviewer_b.zip`, and `package-index.json` in a
new, nonexisting output directory. Each ZIP contains the common frozen OSM
snapshot/catalog/reference/query set, **only that reviewer's blank sheet**,
SHA-256 provenance metadata, and reviewer instructions. It contains no peer
labels, ranks, or analysis results. Do not send the public GitHub repository's
synthetic labels as real-world answers. Transfer each ZIP through a secure
channel to a *different* person. The tool cannot authenticate real independence.

## 4. Reviewer workflow (each reviewer separately)

1. Extract **your** ZIP. Verify filenames and, where operationally necessary,
   the hashes in `package-manifest.json`.
2. Run Savoroute's local web application and open
   `http://127.0.0.1:8001/study-review` (for example, with
   `savoroute web serve --host 127.0.0.1 --port 8001`).
3. Select `review_reference.json` and **your** `reviewer_a.json` or
   `reviewer_b.json`. No file is uploaded. Keep your in-progress JSON in an
   access-controlled folder; browser-based labeling has no autosave.
4. Apply the frozen labeling definition. For a positive, cite exact recorded
   cuisine or other explicit supporting source evidence in the note. Do not
   rely on retrieval ranks, heuristic confidence, model output, or peer labels.
5. For an unassessable case, leave null and send a **separate** issue notice
   with the case/item IDs. No false negative by default. The annotation task
   cannot proceed to evaluation until the protocol addresses unresolved cases.
6. Export and return your final labeled sheet privately to the coordinator.

A practical human workload is **1,320 judgments per reviewer**, 2,640 total
individual decisions before adjudication. Review time is not estimated here:
it depends on evidence sufficiency and the true ambiguity rate.

## 5. Audit completion without exposing peer judgments

Move reviewers' completed files into private locations. Do not publish their
notes or expose the aggregate audit to reviewers before independent completion.

```bash
mkdir -p "$PILOT/reviews"
# Save received sheets as reviewer_a.json and reviewer_b.json under reviews/.
python scripts/study_pilot.py status \
  --study-dir "$STUDY" \
  --reviewer-a "$PILOT/reviews/reviewer_a.json" \
  --reviewer-b "$PILOT/reviews/reviewer_b.json" \
  --output "$PILOT/review-audit.json"
```

The existing Savoroute verifier checks exact pair identities, provenance,
positive-note completeness, and duplicates. `ready_to_merge` must be true.
The count of disagreements is *not* a reliability estimate independent of
query correlation or label prevalence.

## 6. Merge and adjudicate

```bash
savoroute judgments merge \
  --catalog "$STUDY/catalog.json" \
  --workbook "$STUDY/review_template.json" \
  --reviewer-a "$PILOT/reviews/reviewer_a.json" \
  --reviewer-b "$PILOT/reviews/reviewer_b.json" \
  --output "$PILOT/reviews/adjudicated.json"
```

Manually resolve every disagreement with documented *source evidence*, not
retrieval ranks. Agreed labels must not be altered silently. If any pair is
undecidable, **stop**. The schema cannot validly represent a third class and
will refuse finalization with missing labels. Record the adjudicator's role
and conflicts outside the workbook.

## 7. Development analysis first, test analysis only once

```bash
savoroute study analyze \
  --study-dir "$STUDY" \
  --workbook "$PILOT/reviews/adjudicated.json" \
  --plan "$PILOT/analysis-plan.json" \
  --split development \
  --output "$PILOT/development-analysis.json"

python scripts/study_pilot.py summarize \
  --analysis "$PILOT/development-analysis.json" \
  --output "$PILOT/development-summary.md"
```

Before opening held-out outcomes, freeze every post-review decision:
selecting diagnostics, code revision plans, thresholds, and analysis/reporting
criteria. Keep any retrieval changes **outside** this frozen comparison.

Only when eligible:

```bash
savoroute study analyze \
  --study-dir "$STUDY" \
  --workbook "$PILOT/reviews/adjudicated.json" \
  --plan "$PILOT/analysis-plan.json" \
  --split test --allow-test \
  --output "$PILOT/test-analysis.json"

python scripts/study_pilot.py summarize \
  --analysis "$PILOT/test-analysis.json" \
  --output "$PILOT/test-summary.md"
```

**Important:** `--allow-test` cannot *technically enforce* one-time test
access. A coordinator's procedural log must record each held-out access.
Do not choose a model or parameter based on test results and then present its
test performance as an unbiased final assessment.

## 8. Root-cause analysis, not just scores

For each development query with errors, inspect the private `query_errors`
records and classify at least these categories, using *observed evidence*:

| Category | Investigative question |
| --- | --- |
| Coverage/admission | Was a relevant business absent from admitted catalog or filtered? |
| Missing metadata | Was cuisine missing or too generic to support the query? |
| Lexical mismatch | Was the relevant cuisine recorded under aliases, spelling, or another language? |
| Query ambiguity | Did reviewers interpret the information need differently? |
| Ranking | Was a relevant recorded match below k despite being eligible? |
| Zero-match behavior | Does the retrieval implementation return results even when none is relevant? |
| Judgment uncertainty | Is the disagreement about evidence sufficiency rather than ranking? |

Distinguish **annotation uncertainty** from **model error**. A false positive
under the frozen qrels is not proof that a real restaurant does not serve that
cuisine. Record query IDs, item IDs, reference citations, and the relevant
retrieval IDs; do not invent explanations.

## 9. Pilot exit criteria and follow-on benchmark

Pilot completed means: frozen collection verified; analysis plan stored;
reviewer A and B independently complete; all disagreements resolved;
final workbook passes validation; one development analysis; one authorized
test analysis; source-grounded error audit; limitations reported. Otherwise
status is **incomplete** and **no effectiveness claim** is issued.

The study still has only four test queries. For a generalizable follow-up,
collect a substantially larger, diverse query set (different neighborhoods,
cities, cuisines, lengths, open-ended needs, and no-match cases), defined by
an independently specified sampling protocol. Many established IR evaluations
use dozens of topics, but **there is no universal magic minimum**; choose size
from the target estimand and design-stage variability/power analysis. Prefer
new human-authored queries independent of the system developer and tune only
on development data. Separate a new frozen benchmark from this Boston pilot.

### References

- TREC relevance judgment guidance: https://trec.nist.gov/data/reljudge_eng.html
- Sakai, *Topic set size design*, Information Retrieval Journal (2016):
  https://link.springer.com/article/10.1007/s10791-015-9273-z
- Savoroute v0.18 methodology: `docs/statistical-relevance-study.md`
