"""Vector index contracts, round trips, filtering and regression checks."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageStat

from savoroute.data.catalog import load_catalog
from savoroute.media.ingestion import prepare_image_batch, write_image_batch
from savoroute.retrieval.vector import (
    VectorIndexError,
    build_vector_index,
    catalog_fingerprint,
    index_to_dict,
    item_text,
    load_vector_index,
    parse_vector_index,
    search_vectors,
    search_with_encoder,
    validate_catalog,
    write_vector_index,
)

SAMPLE = Path(__file__).resolve().parents[1] / "data/sample"


class FixtureEncoder:
    """Test double, not a pretrained embedding model or an accuracy baseline."""

    model_id = "test-fixture"
    embedding_space_id = "test-fixture@v1"

    def embed_texts(self, texts):
        return [[0.0, 2.0] if "mushroom" in text.casefold() else [3.0, 0.0]
                for text in texts]

    def embed_images(self, paths):
        results = []
        for path in paths:
            with Image.open(path) as image:
                mean_green = ImageStat.Stat(image.convert("RGB")).mean[1]
            results.append([0.0, 2.0] if mean_green > 190 else [3.0, 0.0])
        return results


@pytest.fixture
def prepared(tmp_path):
    base = load_catalog(SAMPLE / "catalog.json")
    batch = prepare_image_batch(SAMPLE / "image_manifest.json", base)
    folder = write_image_batch(batch, tmp_path / "media")
    return load_catalog(folder / "catalog.json"), folder


def test_build_round_trip_and_search(prepared, tmp_path):
    catalog, directory = prepared
    encoder = FixtureEncoder()
    index = build_vector_index(catalog, directory, encoder)
    assert len(index.records) == len(catalog.items) + len(catalog.media)
    assert all(abs(math.hypot(*r.vector) - 1) < 1e-9 for r in index.records)
    assert index.dimension == 2
    assert index.catalog_sha256 == catalog_fingerprint(catalog)
    out = tmp_path / "index.json"
    write_vector_index(index, out)
    restored = load_vector_index(out)
    assert restored == index
    with pytest.raises(Exception, match="already exists"):
        write_vector_index(index, out)
    hits = search_with_encoder(restored, encoder, text="mushroom dish",
                               target="image", catalog=catalog)
    assert hits[0].record_id == "image:image_p002"
    hits = search_with_encoder(restored, encoder, image=directory / "assets/image_p001.png",
                               target="image", catalog=catalog)
    assert hits[0].record_id == "image:image_p001"
    assert search_with_encoder(restored, encoder, text="orange", target="text", k=3)


def test_empty_and_incompatible(prepared):
    catalog, directory = prepared
    idx = build_vector_index(catalog, directory, FixtureEncoder())
    assert len(search_vectors(idx, [1, 0], target="image", k=1)) == 1
    with pytest.raises(VectorIndexError, match="nonzero"):
        search_vectors(idx, [0, 0])
    with pytest.raises(VectorIndexError, match="dimension"):
        search_vectors(idx, [1, 0, 0])
    with pytest.raises(VectorIndexError, match="kind filtering"):
        search_vectors(idx, [1, 0], kind="recipe")
    assert not search_vectors(idx, [1, 0], target="image", kind="restaurant", catalog=catalog)
    with pytest.raises(VectorIndexError, match="differs"):
        validate_catalog(idx, replace(catalog, dataset_name="changed"))
    bad = FixtureEncoder()
    bad.embedding_space_id = "other@v1"
    with pytest.raises(VectorIndexError, match="does not match"):
        search_with_encoder(idx, bad, text="orange")


def test_kind_filter_and_unique_item_pooling(prepared):
    catalog, directory = prepared
    idx = build_vector_index(catalog, directory, FixtureEncoder())
    filtered = search_vectors(idx, [1, 0], target="all", k=30,
                              catalog=catalog, kind="recipe", unique_items=True)
    assert len(filtered) == len({hit.item_id for hit in filtered})
    assert all(catalog.get(hit.item_id).kind == "recipe" for hit in filtered)
    excluded = search_vectors(idx, [1, 0], target="image",
                              exclude=frozenset({"image:image_p001"}))
    assert len(excluded) == 1 and excluded[0].record_id == "image:image_p002"


def test_tampering_and_invalid_vectors(prepared):
    catalog, directory = prepared
    idx = build_vector_index(catalog, directory, FixtureEncoder())
    payload = index_to_dict(idx)
    payload["records"][0]["vector"][0] = 3.0
    with pytest.raises(VectorIndexError, match="unit-normalized"):
        parse_vector_index(payload)
    payload = index_to_dict(idx)
    payload["records"][1]["record_id"] = payload["records"][0]["record_id"]
    with pytest.raises(VectorIndexError, match="duplicate"):
        parse_vector_index(payload)
    payload = index_to_dict(idx)
    payload["records"][0]["vector"][0] = float("nan")
    with pytest.raises(VectorIndexError, match="finite"):
        parse_vector_index(payload)
    payload = index_to_dict(idx)
    payload["unrecognized"] = 1
    with pytest.raises(VectorIndexError, match="index object"):
        parse_vector_index(payload)


def test_model_batch_size_and_dimension(prepared):
    catalog, directory = prepared

    class TooFew(FixtureEncoder):
        def embed_images(self, paths):
            return []

    with pytest.raises(VectorIndexError, match="unexpected"):
        build_vector_index(catalog, directory, TooFew())

    class DimensionMismatch(FixtureEncoder):
        def embed_images(self, paths):
            return [[1, 0, 0] for _ in paths]

    with pytest.raises(VectorIndexError, match="dimensions"):
        build_vector_index(catalog, directory, DimensionMismatch())

    with pytest.raises(VectorIndexError, match="at least one"):
        build_vector_index(catalog, directory, FixtureEncoder(),
                           include_text=False, include_images=False)


def test_local_image_path_security(prepared, tmp_path):
    catalog, directory = prepared
    evil = replace(catalog.media[0], uri="../outside.png")
    with pytest.raises(VectorIndexError, match="relative"):
        build_vector_index(replace(catalog, media=(evil,)), directory, FixtureEncoder(),
                           include_text=False)
    file = tmp_path / "outside.png"
    file.write_bytes(b"test")
    symlink = directory / "assets/escape.png"
    symlink.symlink_to(file)
    evil = replace(catalog.media[0], uri="assets/escape.png")
    with pytest.raises(VectorIndexError, match="escapes"):
        build_vector_index(replace(catalog, media=(evil,)), directory, FixtureEncoder(),
                           include_text=False)


def test_stable_text_document():
    item = load_catalog(SAMPLE / "catalog.json").items[0]
    text = item_text(item)
    assert item.title in text and "Cuisine:" in text
    assert item_text(item) == item_text(item)


def test_index_size_limit(tmp_path):
    file = tmp_path / "too-large.json"
    with file.open("wb") as stream:
        stream.truncate(65 * 1024 * 1024)
    with pytest.raises(VectorIndexError, match="exceeds"):
        load_vector_index(file)


def test_parser_rejects_wrong_record_identity(prepared):
    catalog, directory = prepared
    payload = index_to_dict(build_vector_index(catalog, directory, FixtureEncoder()))
    payload["records"][0]["record_id"] = "image:wrong"
    with pytest.raises(VectorIndexError, match="identity"):
        parse_vector_index(payload)


def test_changed_image_file_is_rejected(prepared):
    catalog, directory = prepared
    idx = build_vector_index(catalog, directory, FixtureEncoder())
    path = directory / "assets/image_p001.png"
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(VectorIndexError, match="image content changed"):
        validate_catalog(idx, catalog, catalog_dir=directory)
