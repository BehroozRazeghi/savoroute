# Local image ingestion

`src/savoroute/media/ingestion.py` imports a bounded manifest of locally stored images. It does not crawl websites or download remote assets.

## Input

`data/sample/image_manifest.json` is a version-1 manifest. Each asset contains `media_id`, an existing catalog `item_id`, a POSIX relative `path`, `source`, `rights_basis` (`owned`, `licensed`, or `permission`), `license`, `attribution`, and optional `caption`. The manifest and catalog must agree on whether the dataset is synthetic. Unknown fields and missing required fields are rejected.

Rights metadata is a declaration provided by the operator. Savoroute **does not verify** an image license or permission. Do not import images unless you have the necessary rights.

## Processing and outputs

```bash
savoroute media ingest \
  --manifest data/sample/image_manifest.json \
  --output-dir data/generated/media-demo

savoroute validate --catalog data/generated/media-demo/catalog.json
```

The output directory contains `catalog.json`, `provenance.json` and `assets/*.png`. Each media URI is relative to the directory containing the catalog. This output directory is created once and never overwritten; choose a different destination for a new batch. The publisher stages files in a temporary sibling directory and then renames the directory on success.

Source images are restricted to the manifest's directory tree, including checks against symlinks that escape that tree. PNG, JPEG, and WebP are accepted; animated assets are not. Source files must be at most 15 MiB, and images at most 24 megapixels. Manifests are limited to 128 KiB, and the combined normalized PNG payload is limited to 64 MiB. All images are EXIF-orientation corrected, converted to RGB (compositing transparency over white), resized so the longest edge is at most 1280 pixels, and written as PNG without source metadata. Identical normalized images in one manifest are rejected. The provenance file records source and normalized SHA-256 hashes, dimensions, image format, declared rights and attribution. These controls bound common inputs; they do not replace a sandboxed image decoding service for untrusted public uploads. See Pillow's security guidance for deployment considerations.

The current one-shot exporter requires an input catalog **without** existing media assets. Incremental asset updates and copy-forward of prior media belong to the subsequent storage milestone. Existing item and catalog schema IDs are not changed.

## Optional text/image encoder

`ClipTextImageEmbedder` implements the existing `JointTextImageEmbedder` interface. It uses a Sentence Transformers CLIP model, lazily loaded on adapter construction. A model revision may be provided to select an exact checkpoint; by default, model loading is local-only and will fail if weights are not cached. The `embedding_space_id` contains the model name and revision string; it is not a cryptographic proof of checkpoint contents.

```bash
python -m pip install -e ".[multimodal]"
```

```python
from pathlib import Path
from savoroute.providers.clip import ClipTextImageEmbedder

encoder = ClipTextImageEmbedder(
    model_id="sentence-transformers/clip-ViT-B-32",
    local_files_only=True,
)
text_vectors = encoder.embed_texts(["a bowl of pasta"])
image_vectors = encoder.embed_images([Path("data/generated/media-demo/assets/image_p002.png")])
```

For a first-time download, explicitly set `local_files_only=False`. For reproducible experiments, pin the checkpoint revision. The CI tests use a fake encoder; they verify adapter behavior and dimensions without downloading model weights. Real model inference and semantic quality are not yet validated by this project.
