"""Benchmark schema, relevance scoring, and CLI smoke tests without model downloads."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageStat

from savoroute.cli import main
from savoroute.data.catalog import load_catalog
from savoroute.evaluation.multimodal import evaluate_multimodal, load_multimodal_benchmark
from savoroute.media.ingestion import prepare_image_batch, write_image_batch
from savoroute.retrieval.vector import (
    VectorIndexError,
    build_vector_index,
    write_vector_index,
)


class FixtureEncoder:
    """Deterministic integration double; not a semantic embedding model."""

    model_id = "test-fixture"
    embedding_space_id = "test-fixture@v1"

    def embed_texts(self, texts):
        return [[0.0, 1.0] if "mushroom" in text.casefold() else [1.0, 0.0]
                for text in texts]

    def embed_images(self, paths):
        vectors = []
        for path in paths:
            with Image.open(path) as image:
                green = ImageStat.Stat(image.convert("RGB")).mean[1]
            vectors.append([0.0, 1.0] if green > 190 else [1.0, 0.0])
        return vectors


SAMPLE = Path(__file__).resolve().parents[1] / "data/sample"


@pytest.fixture
def files(tmp_path):
    batch = prepare_image_batch(SAMPLE / "image_manifest.json", load_catalog())
    root = write_image_batch(batch, tmp_path / "batch")
    catalog = load_catalog(root / "catalog.json")
    index = build_vector_index(catalog, root, FixtureEncoder(), include_text=False)
    target = tmp_path / "index.json"
    write_vector_index(index, target)
    return catalog, index, root, target


def test_retrieval_metrics(files):
    _, index, _, _ = files
    benchmark = load_multimodal_benchmark(SAMPLE / "multimodal_queries_fixture.json")
    summary = evaluate_multimodal(index, FixtureEncoder(), benchmark, k=1)
    assert len(summary.cases) == 4
    assert summary.mean_recall_at_k == 1.0
    assert summary.mrr_at_k == 1.0
    assert summary.mean_ndcg_at_k == 1.0
    assert summary.self_match_cases == 2
    assert summary.as_dict()["synthetic"] is True


def test_relevance_validation(files, tmp_path):
    _, index, _, _ = files
    source = json.loads((SAMPLE / "multimodal_queries_fixture.json").read_text())
    source["cases"][0]["relevant_record_ids"] = ["image:absent"]
    name = tmp_path / "bad.json"
    name.write_text(json.dumps(source))
    bench = load_multimodal_benchmark(name)
    with pytest.raises(VectorIndexError, match="missing image"):
        evaluate_multimodal(index, FixtureEncoder(), bench)


def test_benchmark_rejects_invalid_cases(tmp_path):
    source = json.loads((SAMPLE / "multimodal_queries_fixture.json").read_text())
    source["cases"][0]["exclude_record_ids"] = ["image:image_p001"]
    name = tmp_path / "invalid.json"
    name.write_text(json.dumps(source))
    with pytest.raises(VectorIndexError, match="not excluded"):
        load_multimodal_benchmark(name)


def test_cli_end_to_end_offline(files, tmp_path, monkeypatch, capsys):
    catalog, _, root, index_path = files
    from savoroute.providers import clip
    monkeypatch.setattr(clip, "ClipTextImageEmbedder", lambda *a, **kw: FixtureEncoder())
    out = tmp_path / "from_cli.json"
    assert main(["vectors", "build", "--catalog", str(root / "catalog.json"),
                 "--output", str(out), "--images-only"]) == 0
    assert main(["vectors", "search", "--index", str(index_path), "--catalog",
                 str(root / "catalog.json"), "--text", "orange noodles",
                 "--target", "image", "--limit", "1"]) == 0
    assert '"record_id": "image:image_p001"' in capsys.readouterr().out
    assert main(["vectors", "evaluate", "--index", str(index_path), "--catalog",
                 str(root / "catalog.json"), "--benchmark",
                 str(SAMPLE / "multimodal_queries_fixture.json"), "--at-k", "1"]) == 0
    assert '"self_match_cases": 2' in capsys.readouterr().out
    assert len(catalog.media) == 2


def test_cli_requires_available_weight_backend(files, tmp_path, monkeypatch, capsys):
    _, _, root, _ = files
    from savoroute.providers import clip

    def unavailable(*args, **kwargs):
        raise RuntimeError("model weights unavailable")

    monkeypatch.setattr(clip, "ClipTextImageEmbedder", unavailable)
    assert main(["vectors", "build", "--catalog", str(root / "catalog.json"),
                 "--output", str(tmp_path / "absent.json")]) == 2
    assert "model weights unavailable" in capsys.readouterr().err
