# Joint text/image vector index

Milestone 2b uses the `JointTextImageEmbedder` protocol, which requires that text and image vectors occupy **one embedding space**. The existing `ClipTextImageEmbedder` implements this interface using Sentence Transformers CLIP. Importing Savoroute does not load or download model weights.

## Index contract

A schema-v1 JSON index stores `model.id`, `model.embedding_space_id`, `model.dimension`, a SHA-256 fingerprint of the canonical catalog, and a list of records. Text records have IDs `text:<item_id>`; images have IDs `image:<media_id>`. Each record stores its parent item ID, modality, SHA-256 input hash and a unit-normalized vector. The dataset and catalog schema remain unchanged. Text serialization includes title, description, cuisine, dietary tags, ingredients, and location. Image paths resolve relative to the associated catalog file and must not escape that directory.

The index performs **exact cosine retrieval** using the dot product of unit vectors. It does not use an ANN library. Record ties are sorted by record ID. `--target` restricts results to text or image records. Optional `--kind` filtering uses the matching catalog. `--unique-items` chooses the top-scoring record for each item, rather than adding incompatible modalities or counting multiple images independently. No unverified cosine-distance transformations are used.

Model identity and catalog SHA-256 must match on search and evaluation. The CLI also checks each indexed image file against its stored SHA-256 before querying; this detects asset changes that do not alter the catalog JSON. An explicitly pinned Hugging Face model commit makes model selection more reproducible; a revision alone does not freeze Torch/CUDA versions, image preprocessing or hardware-dependent numerical behavior. Indexing the same catalog again after it changes requires a rebuild. This is a bounded, uncompressed JSON format for experimentation and small datasets, **not** a production-scale ANN database.

## Commands

```bash
python -m pip install -e ".[multimodal]"
savoroute media ingest --manifest data/sample/image_manifest.json \
  --output-dir data/generated/media-demo
savoroute vectors build --catalog data/generated/media-demo/catalog.json \
  --output data/generated/vectors.json --model sentence-transformers/clip-ViT-B-32 \
  --revision YOUR_PINNED_MODEL_COMMIT
savoroute vectors search --index data/generated/vectors.json \
  --catalog data/generated/media-demo/catalog.json --text "mushroom pasta" \
  --target image --revision YOUR_PINNED_MODEL_COMMIT
savoroute vectors search --index data/generated/vectors.json \
  --catalog data/generated/media-demo/catalog.json \
  --image data/generated/media-demo/assets/image_p001.png --target image \
  --revision YOUR_PINNED_MODEL_COMMIT
savoroute vectors evaluate --index data/generated/vectors.json \
  --catalog data/generated/media-demo/catalog.json \
  --benchmark data/sample/multimodal_queries_fixture.json \
  --at-k 2 --revision YOUR_PINNED_MODEL_COMMIT
```

Replace the illustrative revision placeholder with a real commit hash. Without `--allow-download`, model loading only uses locally cached weights. The CLI does not expose a test-double provider; notebook 09 uses an explicitly marked local test double for CI-compatible demonstration.

## Evaluation

The versioned benchmark declares labeled image-record relevance for text or image queries. Metrics are mean Recall@k, MRR@k and nDCG@k, with positive queries only. The sample has two text-to-image queries and two self-retrieval image-to-image queries over fictional illustrations. The self-retrieval cases merely test the data path and should not be interpreted as generalization. Query images can also be independent local assets, allowing real held-out evaluation later. The sample labels are not independent human judgments.

To measure real-world performance, use a documented independently annotated dataset, distinguish self-matches from held-out examples, pin the model and dependency versions, report latency, and measure per-query retrieval failure cases.

## Relationship to the IBM course

The IBM labs separate textual and visual embeddings and store text/image records in persistent vector indexes. That separation is retained. Savoroute instead uses an explicit item/media foreign key, a shared embedding-space contract for cross-modal queries, a validated portable index, and stable parent item identities. The lab's direct calls to Chroma private collections and arbitrary score normalization are not reused. A separate text encoder such as MiniLM must **not** be compared numerically with CLIP image vectors; models must share a defined space or be fused at the ranking level.

See also [IBM course review](ibm-course-review.md) for module-specific design choices.

## Larger persistent backends

The JSON index continues as the portable exact reference. From v0.9.0, `retrieval/dense.py` can convert it into immutable SQLite storage or an optional FAISS HNSW bundle. The change preserves model identity, item/media IDs and the catalog fingerprint. See [persistent vector retrieval](dense-index.md).
