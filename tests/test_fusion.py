"""Item-level fusion, filtering, evaluation, and CLI regression tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from savoroute.cli import main
from savoroute.data.catalog import load_catalog
from savoroute.evaluation.fusion import evaluate_fusion
from savoroute.evaluation.retrieval import BenchmarkError, QueryJudgment, load_benchmark
from savoroute.media.ingestion import prepare_image_batch, write_image_batch
from savoroute.retrieval.fusion import FusionWeights, fuse_rankings, search_fused
from savoroute.retrieval.lexical import SearchFilters
from savoroute.retrieval.vector import VectorIndexError, build_vector_index
from savoroute.services.discovery import DiscoveryService

SAMPLE = Path(__file__).resolve().parents[1] / "data/sample"


class DemoEncoder:
    """Deterministic alignment fixture, not a trained embedding model."""

    model_id = "fusion-test"
    embedding_space_id = "fusion-test@v1"

    def __init__(self):
        self.queries = 0

    def embed_texts(self, texts):
        self.queries += 1
        return [[0.0, 2.0] if "mushroom" in text.casefold() else [2.0, 0.0]
                for text in texts]

    def embed_images(self, paths):
        return [[0.0, 2.0] if "mushroom" in path.name else [2.0, 0.0]
                for path in paths]


@pytest.fixture
def multimodal(tmp_path):
    catalog = load_catalog(SAMPLE / "catalog.json")
    media = write_image_batch(prepare_image_batch(SAMPLE / "image_manifest.json", catalog),
                              tmp_path / "media")
    updated = load_catalog(media / "catalog.json")
    encoder = DemoEncoder()
    idx = build_vector_index(updated, media, encoder)
    encoder.queries = 0
    return updated, media, idx, encoder


def test_rrf_hand_calculation_and_provenance():
    catalog = load_catalog(SAMPLE / "catalog.json")
    ranks = {
        "bm25": [("p001", "text:p001", 10.0), ("p002", "text:p002", 2.0)],
        "text": [("p002", "text:p002", 0.9), ("p001", "text:p001", 0.7)],
        "image": [("p002", "image:demo", 0.8)],
    }
    result = fuse_rankings(catalog, ranks, rrf_k=60)
    assert [row.item.item_id for row in result] == ["p002", "p001"]
    expected = (1 / 62 + 1 / 61 + 1 / 61) / 3
    assert result[0].score == pytest.approx(expected)
    assert [r.source for r in result[0].evidence] == ["bm25", "text", "image"]
    assert sum(row.contribution for row in result[0].evidence) == pytest.approx(result[0].score)
    assert len(result[0].as_dict()["evidence"]) == 3


def test_weighted_ranking_and_tie_stability():
    catalog = load_catalog(SAMPLE / "catalog.json")
    candidates = {"bm25": [("p002", "t2", 8), ("p001", "t1", 5)],
                  "image": [("p001", "i1", 0.7), ("p002", "i2", 0.5)]}
    bm25 = fuse_rankings(catalog, candidates, weights=FusionWeights(3, 0, 1))
    image = fuse_rankings(catalog, candidates, weights=FusionWeights(1, 0, 3))
    assert bm25[0].item.item_id == "p002"
    assert image[0].item.item_id == "p001"
    tied = fuse_rankings(catalog, candidates, weights=FusionWeights(1, 0, 1))
    assert [x.item.item_id for x in tied] == ["p001", "p002"]
    # Unavailable sources are not counted in the denominator.
    only = fuse_rankings(catalog, {"bm25": [("p001", "t1", 5)]})
    assert only[0].score == pytest.approx(1 / 61)


def test_invalid_ranking_inputs():
    catalog = load_catalog(SAMPLE / "catalog.json")
    with pytest.raises(ValueError, match="duplicate item"):
        fuse_rankings(catalog, {"image": [("p001", "i1", 1), ("p001", "i2", .8)]})
    with pytest.raises(ValueError, match="unknown or filtered"):
        fuse_rankings(catalog, {"bm25": [("not-an-item", "t", 5)]})
    with pytest.raises(ValueError, match="finite"):
        fuse_rankings(catalog, {"bm25": [("p001", "t", float("nan"))]})
    with pytest.raises(ValueError, match="zero source weight"):
        fuse_rankings(catalog, {"image": [("p001", "i", 1)]}, weights=FusionWeights(1, 1, 0))
    with pytest.raises(ValueError, match="known retrieval sources"):
        fuse_rankings(catalog, {"other": []})
    for val in (float("nan"), -1.0, float("inf"), True):
        with pytest.raises(ValueError, match="weights"):
            FusionWeights(val, 1, 1)
    with pytest.raises(ValueError, match="positive"):
        FusionWeights(0, 0, 0)
    for bad in (0, -1, 1.5, True):
        with pytest.raises(ValueError):
            fuse_rankings(catalog, {"bm25": []}, rrf_k=bad)


def test_lexical_only_matches_discovery_service():
    catalog = load_catalog(SAMPLE / "catalog.json")
    hits = search_fused(catalog, "creamy mushroom pasta", filters=SearchFilters(kind="recipe"))
    assert hits and hits[0].item.item_id == "p002"
    assert all(len(hit.evidence) == 1 and hit.evidence[0].source == "bm25" for hit in hits)
    assert [hit.item.item_id for hit in DiscoveryService(catalog).rank(
        "creamy mushroom pasta", filters=SearchFilters(kind="recipe"))] == [
            hit.item.item_id for hit in hits]
    assert search_fused(catalog, "quasar xylophone nebula") == ()
    assert search_fused(catalog, " ") == ()


def test_combined_text_and_image_retrieval(multimodal):
    catalog, directory, index, encoder = multimodal
    hits = search_fused(catalog, "mushroom pasta", index=index, encoder=encoder,
                        catalog_dir=directory, filters=SearchFilters(kind="recipe"))
    assert hits[0].item.item_id == "p002"
    assert encoder.queries == 1  # The text query is embedded once, not once per source.
    evidence = {e.source for e in hits[0].evidence}
    assert evidence == {"bm25", "text", "image"}
    assert next(e for e in hits[0].evidence if e.source == "image").record_id == "image:image_p002"
    assert len({row.item.item_id for row in hits}) == len(hits)
    assert all(row.item.kind == "recipe" for row in hits)


def test_hard_filter_applies_to_all_sources(multimodal):
    catalog, directory, index, encoder = multimodal
    filters = SearchFilters(kind="restaurant", location="Sample City", max_price_tier=2,
                            dietary_tags=("vegetarian-options",))
    hits = search_fused(catalog, "mushroom pasta", index=index, encoder=encoder,
                        catalog_dir=directory, filters=filters)
    assert hits
    assert all(row.item.item_id == "r001" or row.item.item_id == "r002" for row in hits)
    assert all(e.source != "image" for row in hits for e in row.evidence)
    assert search_fused(catalog, "mushroom", index=index, encoder=encoder,
                        filters=SearchFilters(location="Nowhere")) == ()


def test_image_items_are_distinct_and_pool_before_truncation(multimodal):
    catalog, directory, _, encoder = multimodal
    extra = replace(catalog.media[0], media_id="extra_p001")
    duplicated = replace(catalog, media=catalog.media + (extra,))
    index = build_vector_index(duplicated, directory, encoder)
    hits = search_fused(duplicated, "orange noodles", index=index, encoder=encoder,
                        weights=FusionWeights(0, 0, 1), pool_size=2,
                        filters=SearchFilters(kind="recipe"))
    assert len(hits) == 2
    assert [row.item.item_id for row in hits] == ["p001", "p002"]
    assert all(len(row.evidence) == 1 for row in hits)


def test_stale_index_and_wrong_encoder_rejected(multimodal):
    catalog, directory, index, encoder = multimodal
    with pytest.raises(VectorIndexError, match="catalog differs"):
        search_fused(replace(catalog, dataset_name="different"), "mushroom",
                     index=index, encoder=encoder)
    wrong = DemoEncoder()
    wrong.embedding_space_id = "wrong"
    with pytest.raises(VectorIndexError, match="does not match"):
        search_fused(catalog, "mushroom", index=index, encoder=wrong)
    with pytest.raises(ValueError, match="either an encoder or a query_vector"):
        search_fused(catalog, "mushroom", index=index, encoder=encoder,
                     query_vector=[1.0, 0.0])
    with pytest.raises(ValueError, match="require an encoder"):
        search_fused(catalog, "mushroom", index=index)
    # Precomputed vectors support deterministic offline retrieval.
    hits = search_fused(catalog, "mushroom", index=index, query_vector=[0, 2])
    assert hits


def test_exclusion_and_no_index_errors(multimodal):
    catalog, directory, index, encoder = multimodal
    with pytest.raises(ValueError, match="require an index"):
        search_fused(catalog, "test", encoder=encoder)
    with pytest.raises(ValueError, match="no enabled retrieval"):
        search_fused(catalog, "test", weights=FusionWeights(0, 1, 0))
    with pytest.raises(ValueError, match="pool_size"):
        search_fused(catalog, "test", pool_size=1001)
    with pytest.raises(ValueError, match="rrf_k"):
        search_fused(catalog, "test", rrf_k=0)
    assert not search_fused(catalog, " ", index=index, encoder=encoder)


def test_fusion_benchmark_and_lexical_only_cli(capsys):
    catalog = load_catalog(SAMPLE / "catalog.json")
    cases = load_benchmark(SAMPLE / "relevance_benchmark.json")
    summary = evaluate_fusion(catalog, cases, at_k=5)
    assert summary.positive_queries > 0 and summary.empty_queries > 0
    assert summary.recall_at_k is not None
    assert summary.correct_empty_rate is not None
    assert summary.as_dict()["method"] == "rrf"
    assert main(["rank", "search", "mushroom pasta", "--kind", "recipe", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result[0]["item_id"] == "p002"
    assert result[0]["evidence"][0]["source"] == "bm25"
    assert main(["rank", "evaluate", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["positive_queries"] == summary.positive_queries
    assert main(["rank", "search", "x", "--bm25-weight", "0"]) == 2
    assert "no enabled" in capsys.readouterr().err
    assert main(["rank", "search", "x", "--index", "not-found.json"]) == 2
    assert "--catalog is required" in capsys.readouterr().err


def test_fusion_evaluation_unknown_and_filtered(multimodal):
    catalog, directory, index, encoder = multimodal
    yes = (QueryJudgment("yes", "mushroom pasta", frozenset({"p002"}),
                         SearchFilters(kind="recipe")),)
    report = evaluate_fusion(catalog, yes, index=index, encoder=encoder,
                             catalog_dir=directory)
    assert report.positive_queries == 1 and report.mrr_at_k == 1
    unknown = (replace(yes[0], relevant_item_ids=frozenset({"unknown"})),)
    with pytest.raises(BenchmarkError, match="unknown relevant"):
        evaluate_fusion(catalog, unknown)
    invalid = (replace(yes[0], filters=SearchFilters(kind="restaurant")),)
    with pytest.raises(BenchmarkError, match="violate filters"):
        evaluate_fusion(catalog, invalid)
    with pytest.raises(BenchmarkError, match="unique IDs"):
        evaluate_fusion(catalog, yes + yes)
    with pytest.raises(BenchmarkError, match="at_k"):
        evaluate_fusion(catalog, yes, at_k=0)


def test_cli_vector_fusion_with_injected_encoder(multimodal, tmp_path, monkeypatch, capsys):
    """Exercise actual CLI parsing, index loading and retrieval without a model download."""
    from savoroute.retrieval.vector import write_vector_index

    _catalog, directory, index, encoder = multimodal
    index_path = tmp_path / "vectors.json"
    write_vector_index(index, index_path)
    import savoroute.providers.clip as clip

    monkeypatch.setattr(clip, "ClipTextImageEmbedder", lambda *args, **kwargs: encoder)
    args = ["--catalog", str(directory / "catalog.json"),
            "--index", str(index_path), "--model", "fusion-test"]
    assert main(["rank", "search", "mushroom pasta", *args,
                 "--kind", "recipe", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result[0]["item_id"] == "p002"
    assert {e["source"] for e in result[0]["evidence"]} == {"bm25", "text", "image"}
    assert main(["rank", "evaluate", *args,
                 "--benchmark", str(SAMPLE / "relevance_benchmark.json"),
                 "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["method"] == "rrf" and summary["positive_queries"] > 0


def test_bm25_only_with_index_does_not_load_model(multimodal, tmp_path, monkeypatch, capsys):
    from savoroute.retrieval.vector import write_vector_index

    _catalog, directory, index, _encoder = multimodal
    path = tmp_path / "vectors.json"
    write_vector_index(index, path)
    import savoroute.providers.clip as clip

    def fail(*args, **kwargs):
        raise AssertionError("CLIP should not load when vector weights are zero")

    monkeypatch.setattr(clip, "ClipTextImageEmbedder", fail)
    assert main(["rank", "search", "mushroom pasta", "--json",
                 "--catalog", str(directory / "catalog.json"),
                 "--index", str(path), "--text-weight", "0",
                 "--image-weight", "0"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output and all(e["source"] == "bm25" for row in output
                          for e in row["evidence"])
