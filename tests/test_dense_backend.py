"""Persistent vector backend integrity, equivalence, and fusion regression tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from savoroute.cli import main
from savoroute.data.catalog import load_catalog
from savoroute.evaluation.dense import benchmark_dense, generated_records
from savoroute.evaluation.fusion import evaluate_fusion
from savoroute.evaluation.retrieval import load_benchmark
from savoroute.media.ingestion import prepare_image_batch, write_image_batch
from savoroute.retrieval.dense import (
    DenseIndexError,
    convert_vector_index,
    load_dense_index,
    search_dense,
    validate_dense_catalog,
    write_dense_index,
)
from savoroute.retrieval.fusion import search_fused
from savoroute.retrieval.lexical import SearchFilters
from savoroute.retrieval.vector import (
    VectorIndexError,
    build_vector_index,
    search_vectors,
    write_vector_index,
)

SAMPLE = Path(__file__).resolve().parents[1] / "data/sample"


class Encoder:
    model_id = "dense-test"
    embedding_space_id = "dense-test@1"

    def embed_texts(self, texts):
        return [[0.0, 1.0] if "mushroom" in text.casefold() else [1.0, 0.0]
                for text in texts]

    def embed_images(self, paths):
        return [[0.0, 1.0] if "mushroom" in p.name else [1.0, 0.0] for p in paths]


@pytest.fixture
def prepared(tmp_path):
    catalog = load_catalog(SAMPLE / "catalog.json")
    media_dir = write_image_batch(
        prepare_image_batch(SAMPLE / "image_manifest.json", catalog), tmp_path / "media"
    )
    enriched = load_catalog(media_dir / "catalog.json")
    reference = build_vector_index(enriched, media_dir, Encoder())
    bundle = convert_vector_index(reference, tmp_path / "dense")
    return enriched, media_dir, reference, bundle


def test_sqlite_round_trip_matches_json_reference(prepared):
    catalog, _, index, bundle = prepared
    assert bundle.count == 14
    assert bundle.dimension == 2
    assert bundle.engine == "sqlite"
    assert load_dense_index(bundle.root) == bundle
    for modality in ("image", "text", "all"):
        for unique in (False, True):
            actual = search_dense(bundle, [0, 1], target=modality, k=5, catalog=catalog,
                                  unique_items=unique)
            expected = search_vectors(index, [0, 1], target=modality, k=5,
                                      catalog=catalog, unique_items=unique)
            assert [row.record_id for row in actual] == [row.record_id for row in expected]
            for a, b in zip(actual, expected, strict=True):
                assert a.score == pytest.approx(b.score, abs=1e-6)


def test_filter_and_exclude(prepared):
    catalog, _, _, bundle = prepared
    hits = search_dense(bundle, [1, 0], target="text", k=8,
                        catalog=catalog, kind="recipe",
                        exclude=frozenset({"text:p001"}),
                        allowed_item_ids=frozenset({"p001", "p003", "p005"}))
    assert {h.item_id for h in hits} == {"p003", "p005"}
    with pytest.raises(DenseIndexError, match="kind requires"):
        search_dense(bundle, [1, 0], kind="recipe")
    with pytest.raises(VectorIndexError, match="dimension"):
        search_dense(bundle, [1, 0, 0])


def test_source_hashes_and_catalog_identity(prepared):
    catalog, directory, _, bundle = prepared
    validate_dense_catalog(bundle, catalog, catalog_dir=directory)
    other = replace(catalog, dataset_name="not-the-original")
    with pytest.raises(DenseIndexError, match="catalog differs"):
        validate_dense_catalog(bundle, other)
    asset = directory / "assets/image_p001.png"
    asset.write_bytes(asset.read_bytes() + b"tail")
    with pytest.raises(DenseIndexError, match="image content changed"):
        validate_dense_catalog(bundle, catalog, catalog_dir=directory)


def test_modified_bundle_is_rejected(prepared):
    _, _, _, bundle = prepared
    file = bundle.root / "vectors.sqlite"
    with file.open("ab") as stream:
        stream.write(b"tampering")
    with pytest.raises(DenseIndexError, match="altered"):
        load_dense_index(bundle.root)


def test_duplicate_ids_and_empty_bundle_do_not_publish(tmp_path):
    row = next(generated_records(1, 2, 1))
    options = dict(model_id="test", embedding_space_id="space", dimension=2,
                   dataset_name="sample", synthetic=True, catalog_sha256="0" * 64)
    with pytest.raises(DenseIndexError, match="strictly increasing"):
        write_dense_index([row, row], tmp_path / "duplicate", **options)
    assert not (tmp_path / "duplicate").exists()
    with pytest.raises(DenseIndexError, match="empty index"):
        write_dense_index([], tmp_path / "empty", **options)
    with patch("savoroute.retrieval.dense._faiss", side_effect=DenseIndexError("requires FAISS")):
        with pytest.raises(DenseIndexError, match="requires"):
            write_dense_index([row], tmp_path / "missing-faiss", engine="faiss-hnsw", **options)


def test_larger_than_json_record_limit_with_stream(tmp_path):
    # Reaches beyond the JSON reference's 20k record cap without materializing rows.
    bundle = write_dense_index(
        generated_records(20_005, 2, 14), tmp_path / "large",
        model_id="test", embedding_space_id="space", dimension=2,
        dataset_name="synthetic", synthetic=True, catalog_sha256="0" * 64,
    )
    assert bundle.count == 20_005
    assert search_dense(bundle, [1.0, 0.0], k=3)


def test_rrf_reuses_dense_backend_and_evaluation(prepared):
    catalog, directory, ref, bundle = prepared
    for idx in (ref, bundle):
        hits = search_fused(catalog, "mushroom pasta", index=idx, encoder=Encoder(),
                            catalog_dir=directory, filters=SearchFilters(kind="recipe"))
        assert hits[0].item.item_id == "p002"
        assert set(e.source for e in hits[0].evidence) == {"bm25", "text", "image"}
    gold = load_benchmark(SAMPLE / "relevance_benchmark.json")
    summary = evaluate_fusion(catalog, gold, index=bundle, encoder=Encoder(),
                              catalog_dir=directory)
    assert summary.positive_queries > 0


def test_backend_cli(prepared, tmp_path, capsys):
    _, directory, reference, _ = prepared
    ref_file = tmp_path / "reference.json"
    write_vector_index(reference, ref_file)
    destination = tmp_path / "built"
    assert main(["backend", "build", "--index", str(ref_file), "--output-dir",
                 str(destination)]) == 0
    output = capsys.readouterr().out
    assert "14 records" in output
    assert main(["backend", "search", "--bundle", str(destination), "--catalog",
                 str(directory / "catalog.json"), "--vector", "[0,1]",
                 "--target", "image"]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert len(hits) == 2 and {row["item_id"] for row in hits} == {"p001", "p002"}
    assert main(["rank", "search", "mushroom pasta", "--catalog",
                 str(directory / "catalog.json"), "--index", str(destination),
                 "--text-weight", "0", "--image-weight", "0", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)
    assert main(["backend", "benchmark", "--records", "60", "--dimension", "8",
                 "--queries", "4", "--at-k", "3"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mean_exact_overlap_at_k"] == 1.0


def test_synthetic_latency_report_and_invalid_options():
    result = benchmark_dense(records=80, dimension=8, queries=5, k=4, seed=11)
    assert result.mean_exact_overlap_at_k == pytest.approx(1.0)
    assert result.p95_ms >= result.median_ms >= 0
    for bad in (0, True, 1.2, 999999999):
        with pytest.raises(ValueError, match="parameters"):
            benchmark_dense(records=bad)


def test_optional_faiss_real_backend_if_installed(tmp_path):
    pytest.importorskip("faiss")
    pytest.importorskip("numpy")
    bundle = write_dense_index(
        generated_records(100, 16, 8), tmp_path / "ann", engine="faiss-hnsw",
        model_id="test", embedding_space_id="space", dimension=16,
        dataset_name="synthetic", synthetic=True, catalog_sha256="0" * 64,
    )
    query = next(generated_records(100, 16, 8)).vector
    ann_hits = search_dense(bundle, query, k=10)
    assert ann_hits[0].item_id == "item-00000000"


def test_bundle_write_does_not_overwrite(prepared):
    _, _, reference, bundle = prepared
    with pytest.raises(DenseIndexError, match="already exists"):
        convert_vector_index(reference, bundle.root)
    assert load_dense_index(bundle.root) == bundle


def test_bundle_manifest_version_and_data_are_checked(prepared):
    _, _, _, bundle = prepared
    manifest = bundle.root / "manifest.json"
    payload = json.loads(manifest.read_text())
    payload["schema_version"] = 999
    manifest.write_text(json.dumps(payload))
    with pytest.raises(DenseIndexError, match="unsupported bundle"):
        load_dense_index(bundle.root)


def test_relevance_challenge_has_valid_judgments():
    catalog = load_catalog(SAMPLE / "catalog.json")
    cases = load_benchmark(SAMPLE / "relevance_challenge_v1.json")
    assert len(cases) == 42
    assert {c.case_id.split("-", 1)[0] for c in cases} == {
        "literal", "paraphrase", "multi", "negative"
    }
    allowed = {item.item_id for item in catalog.items}
    assert all(case.relevant_item_ids <= allowed for case in cases)
    assert sum(not case.relevant_item_ids for case in cases) == 8
