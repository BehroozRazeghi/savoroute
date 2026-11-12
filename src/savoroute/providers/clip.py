"""Optional joint text/image encoder using Sentence Transformers CLIP.

Model downloads are never triggered merely by importing the Savoroute package.
An exact model revision can be provided for reproducible model selection.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any


class ClipTextImageEmbedder:
    """Encode text and RGB images into one model-defined embedding space."""

    def __init__(
        self,
        model_id: str = "sentence-transformers/clip-ViT-B-32",
        *,
        revision: str | None = None,
        local_files_only: bool = True,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("install savoroute[multimodal] for CLIP embeddings") from exc
        self.model_id = model_id
        self.embedding_space_id = f"{model_id}@{revision or 'unversioned'}"
        self._dimension: int | None = None
        self._model = SentenceTransformer(
            model_id, revision=revision, local_files_only=local_files_only,
            trust_remote_code=False,
        )

    def _vectors(self, inputs: list[Any]) -> list[list[float]]:
        if not inputs:
            return []
        result = self._model.encode(inputs, convert_to_numpy=True, normalize_embeddings=True)
        vectors = result.tolist()
        if len(vectors) != len(inputs):
            raise ValueError("embedding batch size mismatch")
        if not vectors or not all(isinstance(row, list) and row for row in vectors):
            raise ValueError("embeddings must be nonempty vectors")
        dimensions = {len(row) for row in vectors}
        if len(dimensions) != 1:
            raise ValueError("embedding dimensions differ")
        dimension = dimensions.pop()
        if self._dimension is not None and dimension != self._dimension:
            raise ValueError("embedding dimensions changed between modalities")
        if any(not isinstance(value, (float, int)) or not math.isfinite(value)
               for row in vectors for value in row):
            raise ValueError("embeddings contain non-finite values")
        self._dimension = dimension
        return [[float(value) for value in row] for row in vectors]

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise ValueError("embedding inputs must be nonempty strings")
        return self._vectors(list(texts))

    def embed_images(self, paths: Sequence[Path]) -> list[list[float]]:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("install savoroute[images] for image processing") from exc
        with ExitStack() as stack:
            images = [stack.enter_context(Image.open(path)).convert("RGB") for path in paths]
            return self._vectors(images)
