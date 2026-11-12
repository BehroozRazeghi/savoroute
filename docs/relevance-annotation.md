# Relevance judgments and evaluation

## Current datasets

`data/sample/relevance_benchmark.json` is the original small fictional demonstration. `data/sample/relevance_challenge_v1.json` contains 42 **curated fictional queries** with binary item-level judgments: 12 literal, 12 paraphrased, 10 multi-answer, and 8 no-match cases. It adds coverage of ambiguity and lexical mismatch, but it is neither independently annotated nor representative of real user queries. No model weights or fusion parameters have been tuned against these cases.

Both files use the existing `benchmark_version: 1` format. Query relevance is defined against canonical `item_id` values after hard metadata filters. A no-match judgment means there is no relevant item in the selected catalog, not that a system can infer a universal rejection threshold. For vector-based systems without calibrated rejection, correct-empty rates should be interpreted with particular care.

Run the existing evaluation API without model downloads:

```bash
savoroute rank evaluate --benchmark data/sample/relevance_challenge_v1.json \
  --bm25-weight 1 --text-weight 0 --image-weight 0 --json
python scripts/evaluate_challenge.py
```

The script reports each synthetic query group separately. Do not quote its metrics as real-world performance.

## Real-world annotation protocol

1. **Specify the task:** restaurant discovery versus recipe retrieval, geographic scope, supported language, and intended filters. Decide whether relevance is binary or graded before collecting judgments.
2. **Freeze inputs:** license-review and snapshot catalog records, source references, media rights, normalized item identities, and dataset fingerprints. Exclude private reviews and user data without permission.
3. **Sample queries independently of retrieval outputs:** use held-out queries reflecting actual user tasks and stratify by literal, paraphrase, ambiguous, constrained, and no-result intent. Document sampling weights and limitations.
4. **Annotate blind to system ranks:** for each query, label relevant canonical items with evidence or rationale. Use two independent annotators on a subset, resolve disagreements and report agreement; do not silently infer labels from the search system's output.
5. **Maintain disjoint development and test splits:** avoid sharing near-duplicate item/query templates between tuning and final evaluation. Freeze test judgments before selecting RRF weights, thresholds, or ANN parameters.
6. **Evaluate per stratum:** report Recall@k, MRR@k, nDCG@k, no-result behavior, bootstrap uncertainty, and latency. Compare lexical, exact vector, and ANN modes with the same catalog and query set. Report ANN agreement against an exact ranking separately from retrieval relevance.

`QueryJudgment` and `evaluate_fusion` accept externally labeled queries using the version-1 benchmark schema. The schema itself does not store evidence spans, annotator identities, or graded labels; those records need a separately versioned annotation artifact before publication. The provided fictional judgments are regression and teaching fixtures, not a substitute for this process.


The new two-reviewer workbook/export workflow is documented in [relevance workflow](relevance-workflow.md). It is distinct from the older synthetic regression judgments and does not supply independent real labels.
