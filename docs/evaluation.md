# Retrieval evaluation

The sample benchmark contains 16 queries against 12 fictional catalog items. Fourteen queries have one relevant item; two specify no relevant item. Results describe this fixture only. They do not estimate search quality on real food or restaurant data.

## Rankers

Tokenization lowercases text and extracts `[a-z0-9]+`. Query terms are deduplicated before scoring.

**Weighted overlap** counts distinct query terms present in each field. The implemented weights are: title 5, cuisine 3, dietary tags 2, and description, location, and ingredients 1 each. A term present in several fields contributes to each field's score.

**BM25** uses the following form for a document $d$ and unique query-term set $Q$:

$$
\mathrm{score}(d,Q)=\sum_{t\in Q}\log\!\left(1+\frac{N-n_t+0.5}{n_t+0.5}\right)
\frac{f(t,d)(k_1+1)}{f(t,d)+k_1\left(1-b+b\frac{|d|}{\overline L}\right)},
$$

where $k_1=1.5$, $b=0.75$, $N$ is the number of catalog records, $n_t$ is the number containing $t$, and $\overline L$ is the mean document length. The document is constructed by concatenating the title three times, cuisines twice, and description, dietary tags, ingredients, and location once. Field repetition is a heuristic, not BM25F. Corpus statistics are calculated over all input records, independent of the result filters.

Only positive-score eligible hits are returned, sorted by decreasing score and then `item_id`. Scores are not probabilities and are not comparable between methods or query texts.

## Metrics

For the set $R$ of relevant item IDs and the top-$k$ result list $L_k$:

- **Recall@k:** $|R\cap L_k|/|R|$ when $R$ is nonempty.
- **MRR@k:** reciprocal of the first relevant rank, or zero when no relevant result appears in the first $k$ positions.
- **nDCG@k:** binary-relevance DCG normalized by the ideal DCG over the first $\min(k,|R|)$ positions.
- **Correct empty-result rate:** fraction of zero-relevance queries for which the search returns no hits.

The first three reported values are macro-averages over positive queries. The empty-result rate uses the negative queries only. If the relevant group is absent, its aggregate is `null` (`N/A` in the CLI). Each marked relevant ID must be in the catalog and eligible under the query's filters.

```bash
savoroute evaluate --method both --at-k 5
savoroute evaluate --method bm25 --at-k 3 --json
python scripts/run_offline_baselines.py --output outputs/phase0-metrics.json
```

## Limits of the baseline

The relevance labels were constructed for the small fictional catalog; they are not independent judgments. One relevant item per positive query makes Recall@k effectively a hit indicator in this fixture. Paraphrased queries expose lexical failures but do not establish a representative semantic-search benchmark. No-match tests measure whether the system returns an empty list, not whether a confidence threshold is calibrated.

Subsequent evaluations will require licensed data, independently labeled queries, explicit train/evaluation separation where applicable, filter-specific cases, multilingual coverage, and latency/resource measurements. Multimodal retrieval will be evaluated by canonical item ID with separate text, image, and fused retrieval results.
