# Persistent vector retrieval

Savoroute supports two persistent search representations:

- **JSON reference index:** the v0.7 format, bounded to 20,000 vectors, with exact cosine search in Python. It remains the correctness baseline.
- **Dense bundle:** an immutable directory containing SQLite vector/record storage and a small JSON manifest. An optional FAISS HNSW graph accelerates approximate nearest-neighbor search. The indexed vectors use float32; the reference JSON keeps Python float precision.

The bundle format does not replace catalog schema v1 or stable item/media identifiers. The existing ranking service accepts either representation, so the source-specific ranked lists and reciprocal rank fusion remain unchanged.

## Storage contract

```
bundle/
├── manifest.json
├── vectors.sqlite
└── hnsw.faiss         # only for engine=faiss-hnsw
```

`manifest.json` records schema version 1, engine, model ID, embedding-space ID, vector dimension, dataset name, synthetic flag, catalog SHA-256, record count, HNSW parameters, and SHA-256 hashes of the stored files. The SQLite `records` table maps deterministic integer ordinals to `record_id`, `item_id`, modality, input SHA-256, and a little-endian float32 embedding BLOB. Records must be supplied in strictly increasing `record_id` order. The writer publishes a **new directory** after successful generation and does not overwrite an existing bundle.

A bundle is checked for file changes when loaded. Catalog fingerprints are validated before ranking; with a catalog directory, image hashes are also checked. The SQLite reader uses a read-only, immutable connection. A hash detects accidental or unauthorized modification relative to the local manifest; it is **not** a digital signature and cannot prove provenance against an attacker who replaces both file and manifest.

### Backends

**SQLite exact:** scans stored vectors and computes cosine similarity using their normalized float32 contents. It supports streaming index construction beyond the JSON record cap without loading the whole corpus. Search is still O(Nd); SQLite is a durable metadata and vector store, not an approximate nearest-neighbor engine.

**FAISS HNSW:** optionally stores a graph built with inner-product similarity over unit vectors. A candidate ordinal maps back to source/item IDs through SQLite. `M`, `efConstruction`, and `efSearch` are exposed as parameters. Candidate retrieval is approximate, and filters are applied after graph search, with adaptive candidate overfetch. No claim of exhaustive filtered results is made. HNSW results, build behavior, and latency can vary by FAISS version, CPU and thread configuration. Model revisions and library versions should be recorded when publishing benchmarks.

FAISS serialized indexes should only be read from trusted local bundles. Do not load arbitrary submitted `.faiss` files. The local manifest verifies integrity relative to the manifest but is not an authenticity guarantee.

## CLI

Build the reference as usual with `savoroute vectors build`, then convert it:

```bash
savoroute backend build \
  --index data/generated/m2b/vectors.json \
  --output-dir data/generated/m2b/sqlite-bundle

savoroute backend search \
  --bundle data/generated/m2b/sqlite-bundle \
  --vector '[0.1,0.2]' --target image
```

The last command is illustrative; the query vector must match the actual index dimension. For application queries, pass a bundle directory to `savoroute rank search --index ...` and use the same CLIP model and revision as the source index.

Optional FAISS installation:

```bash
python -m pip install -e '.[ann]'
savoroute backend build --index data/generated/m2b/vectors.json \
  --output-dir data/generated/m2b/hnsw-bundle --engine faiss-hnsw \
  --hnsw-m 24 --ef-construction 120 --ef-search 96
```

The JSON conversion command inherits the reference index's 20k record limit. For larger datasets, Python code can call `write_dense_index` with an ordered stream of `VectorRecord` values. The current model embedding pipeline is still batch-oriented; streaming embedding production is separate work.

## Performance measurement

```bash
savoroute backend benchmark --engine sqlite \
  --records 1000 --dimension 32 --queries 20 --at-k 10 --seed 7

# With the optional dependency installed:
savoroute backend benchmark --engine faiss-hnsw \
  --records 1000 --dimension 32 --queries 20 --at-k 10 --seed 7
```

The benchmark generates deterministic synthetic unit vectors, builds a new bundle, warms up search, and reports build time, median and p95 query latency, and mean set overlap of top-k results against the JSON exact reference. Search timing includes backend opening/decoding overhead but not embedding generation or file creation. It is a local microbenchmark, not an end-to-end application SLO. No fixed latency thresholds are asserted in CI. The harness bounds corpus size because it also constructs a JSON reference. A separate test streams over 20,000 records into SQLite.

To reproduce a reported result, retain the command and machine specification, Python/SQLite/FAISS/NumPy versions, model revision, input hashes, warm-up and query counts. Compare ANN recall and latency across `efSearch` rather than assuming a specific speedup.

## Limits

- The JSON index is the strict exact reference. Float32 storage can introduce small score changes and near-tie reordering.
- The current local SQLite exact search loads vector rows in a single query; it is not low-latency search for millions of vectors.
- The service retains the current Python BM25 implementation, whose document statistics are recomputed per query. Increasing vector scale alone does not make the entire retrieval stack scalable.
- ANN functionality and speed must be validated on the target system with a real FAISS installation.
- The benchmark vectors and the supplied food catalog are synthetic. Neither measures food-search relevance on real sources.
