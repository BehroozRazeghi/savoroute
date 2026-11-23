# Catalog-bound lexical retrieval: correctness and latency

**Release:** v0.22.0. **Scope:** local CPU indexing and repeated search. No new retrieval model or evaluation labels.

## Implementation

The lexical index is constructed by `LexicalIndex.build(catalog.items)` and held for the lifetime of a `DiscoveryService` instance. `create_app` constructs one service at application startup. The following paths share that index:

- `DiscoveryService.search` → weighted overlap or BM25.
- `DiscoveryService.rank` → lexical arm of item-level RRF, plus optional vector sources.
- `DiscoveryService.recommend` → lexical arm before existing preference reranking.

The public `search_catalog(items, ...)` remains available and, when called independently, builds a temporary index per call. An optional `lexical_index=` must be bound to the **identical immutable item tuple**, not merely items with the same IDs. A changed catalog must be reloaded into a new service. No global/process-wide cache or background updates are introduced. The implementation stores term counts, postings, field token sets, document lengths, and corpus document frequencies in memory. Index construction has nonzero startup time and memory cost.

The score formulas and deterministic result ordering remain unchanged. The BM25 field weighting is **text repetition**, not BM25F: title 3×, cuisines 2×, other searchable fields 1×. IDF is calculated against the **entire** catalog (including filtered-out records). Query tokens are deduplicated. Unknown metadata cannot satisfy hard filters; results with zero score are excluded; ties are broken by `item_id`.

## Regression gates

`tests/test_lexical_index_m5.py` includes an independent original-formula reference implementation, exact score/order/matched-term parity across both methods and multiple hard filters, seeded synthetic query coverage, stale-index rejection, and shared-service integration. Tests on fictional fixtures demonstrate numerical preservation; they do not validate restaurant information or user relevance.

## Performance microbenchmark

From the repository root, install the development dependencies:

```bash
python -m pip install -e ".[api,dev]"
```

Run:

```bash
python scripts/benchmark_lexical.py --loops 20 --warmup 3
python scripts/benchmark_lexical.py --repeat 50 --loops 20 --warmup 3 \
  --output outputs/local-lexical-benchmark.json
```

Create `outputs/` first if you want a JSON file. The report path must **not** already exist. The script checks identical outputs and scores before timing both paths:

1. **Stateless:** `search_catalog(...)` — constructs one temporary index for each query.
2. **Indexed:** one `LexicalIndex.build(...)` followed by repeated `index.search(...)` calls.

Both arms use the **same v0.22.0 implementation**. This is *not* a direct v0.21.1 versus v0.22.0 comparison. The index build time is reported separately. Queries are fixed public examples; expansion uses repeated fictional records with unique synthetic IDs; repetition is only a load test, never expanded restaurant coverage. `p50` is the sample median, and `p95` is the order-statistic nearest-rank percentile of per-query CPU wall-clock observations. Local OS scheduling, CPU power and caching influence measurements. Neither report is a production SLA, independent benchmark, or evidence of higher retrieval quality.

## Remaining gates

- Complete independent relevance review on frozen real-data queries. Unjudged data must not be counted as nonrelevant by default. Pooling and incomplete judgments require careful methodological treatment.
- Benchmark catalog loading, indexing memory, concurrent reads, endpoint end-to-end latency, and larger non-duplicated datasets separately, with machine/software specifications and repeated runs.
- Extend search quality only when error analysis demonstrates a real user-relevant deficiency; use held-out queries and paired comparisons before declaring an improvement.
