"""Tests use a fake model; CI does not download weights or claim semantic accuracy."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from savoroute.providers.clip import ClipTextImageEmbedder


class ArrayLike:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class FakeModel:
    def __init__(self, model_name, **kwargs):
        self.model_name = model_name
        self.kwargs = kwargs

    def encode(self, data, **kwargs):
        assert kwargs["normalize_embeddings"]
        values = [[0.1, 0.9] if isinstance(x, str) else [0.9, 0.1] for x in data]
        return ArrayLike(values)


def test_joint_encoder_contract(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        SimpleNamespace(SentenceTransformer=FakeModel))
    encoder = ClipTextImageEmbedder(revision="example-commit")
    assert encoder.embedding_space_id.endswith("@example-commit")
    assert encoder._model.kwargs["local_files_only"] is True
    assert encoder._model.kwargs["trust_remote_code"] is False
    assert encoder.embed_texts(["a bowl"]) == [[0.1, 0.9]]
    from PIL import Image
    path = tmp_path / "plate.png"
    Image.new("RGB", (10, 10), "green").save(path)
    assert encoder.embed_images([path]) == [[0.9, 0.1]]
    assert encoder.embed_texts([]) == []
    assert encoder.embed_images([]) == []


def test_empty_text_rejected(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        SimpleNamespace(SentenceTransformer=FakeModel))
    encoder = ClipTextImageEmbedder()
    with pytest.raises(ValueError, match="nonempty"):
        encoder.embed_texts([""])


class BadModel(FakeModel):
    def encode(self, data, **kwargs):
        return ArrayLike([[math.nan, 0.1] for _ in data])


def test_nonfinite_embeddings_rejected(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        SimpleNamespace(SentenceTransformer=BadModel))
    encoder = ClipTextImageEmbedder()
    with pytest.raises(ValueError, match="non-finite"):
        encoder.embed_texts(["text"])


class InconsistentDimensions(FakeModel):
    def encode(self, data, **kwargs):
        if isinstance(data[0], str):
            return ArrayLike([[0.3, 0.7] for _ in data])
        return ArrayLike([[0.2, 0.3, 0.5] for _ in data])


def test_cross_modal_dimension_mismatch(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        SimpleNamespace(SentenceTransformer=InconsistentDimensions))
    encoder = ClipTextImageEmbedder()
    encoder.embed_texts(["text"])
    from PIL import Image
    image = tmp_path / "test.png"
    Image.new("RGB", (8, 8)).save(image)
    with pytest.raises(ValueError, match="dimensions changed"):
        encoder.embed_images([Path(image)])
