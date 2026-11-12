# Item-level rank fusion

`retrieval/fusion.py` combines the existing BM25, text-vector, and image-vector backends without making their native scores directly comparable. The canonical unit of retrieval is `CatalogItem.item_id`; an image is evidence for its parent item, not an independent recommendation.

## Algorithm

1. Apply the catalog's hard filters (`kind`, cuisine, location, maximum price tier, and required dietary tags) to obtain the admissible item IDs. Unknown metadata never satisfies an explicit constraint.
2. Retrieve up to `pool_size` positive-score BM25 item hits. In parallel, when a compatible vector index is supplied, encode the text query once and retrieve up to `pool_size` distinct item hits from each of the text and image modalities. The image rank uses the highest cosine-scoring record per item; item deduplication precedes pool truncation.
3. Fuse independent rank lists by weighted reciprocal rank fusion. For item `i`:

   \[
   S(i) = \sum_{s \in A(i)} \frac{w_s / \sum_{t \in A} w_t}{k_0+r_s(i)}.
   \]

   `A` is the set of enabled, nonempty sources; `A(i)` is the subset that retrieved item `i`; `r_s(i)` is its 1-based rank in source `s`. Defaults: `k_0=60`, `pool_size=50`, all three weights `1`. Scores are positive evidence weights, **not calibrated probabilities**.
4. Sort descending by RRF score, then ascending by `item_id` for deterministic ties. Each result includes its source record ID, native score, rank, and RRF contribution.

Missing modalities are excluded from the weight denominator. A disabled source has weight zero. An empty BM25 list does not force the vector lists to be empty. Only one result per catalog item is returned. The index must match the catalog fingerprint and query encoder identity; the CLI additionally verifies local media content hashes.

## API and CLI

```python
from savoroute.data.catalog import load_catalog
from savoroute.retrieval.fusion import FusionWeights, search_fused
from savoroute.retrieval.lexical import SearchFilters

catalog = load_catalog()
hits = search_fused(catalog, "mushroom pasta", filters=SearchFilters(kind="recipe"),
                    weights=FusionWeights(bm25=1, text=1, image=1))
```

Without an index, this is the BM25-only ranking (other weights are inactive). For multimodal search, provide a v0.7.0 `VectorIndex` and either a matching `JointTextImageEmbedder` or a precomputed query vector. Index construction and CLIP caching are described in [vector-index.md](vector-index.md).

```bash
savoroute rank search "mushroom pasta" --kind recipe --json
savoroute rank evaluate --json

# After a real CLIP index has been built:
savoroute rank search "mushroom pasta" \
  --catalog data/generated/m2b/media/catalog.json \
  --index data/generated/m2b/vectors.json --kind recipe --json
savoroute rank evaluate --catalog data/generated/m2b/media/catalog.json \
  --index data/generated/m2b/vectors.json \
  --benchmark data/sample/relevance_benchmark.json
```

Use `--revision` matching the vector-index model revision. Downloading model weights requires `--allow-download`. The index remains exact cosine over JSON, not a scalable production vector service.

## Evaluation and limitations

`evaluation/fusion.py` uses the same item-level query judgments as the lexical benchmark. Binary Recall@k, MRR@k, and nDCG@k are macro-averaged over positive queries. The correct-empty rate is computed separately over zero-relevance cases. No real-world benchmark is included. With a vector source enabled, nearest-neighbor search generally returns some item even for an irrelevant query, so no-match performance requires a separately evaluated acceptance criterion. We do not claim that RRF improves accuracy over BM25 without a representative held-out dataset.

Weights, pool size, and `k_0` should be chosen using validation data, not tuned on the final test set. For large catalogs, the next development stage will replace the JSON index with a backend adapter and measure query latency and retrieval quality. No provider-specific filtering is delegated to a model.
