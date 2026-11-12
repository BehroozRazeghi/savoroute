"""Local image ingestion: validation, provenance, and atomic publication."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image

from savoroute.data.catalog import load_catalog
from savoroute.media.ingestion import (
    MediaIngestionError,
    parse_image_manifest,
    prepare_image_batch,
    write_image_batch,
)

SAMPLE = Path(__file__).resolve().parents[1] / "data/sample"


def _fixture(tmp_path: Path) -> Path:
    """Copy the committed original illustrations into a private test directory."""
    (tmp_path / "media").mkdir()
    for path in (SAMPLE / "media").glob("*.png"):
        (tmp_path / "media" / path.name).write_bytes(path.read_bytes())
    path = tmp_path / "manifest.json"
    path.write_bytes((SAMPLE / "image_manifest.json").read_bytes())
    return path


def _modify(path: Path, change) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    change(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_manifest_and_references():
    manifest = parse_image_manifest(json.loads((SAMPLE / "image_manifest.json").read_text()),
                                    load_catalog())
    assert len(manifest.sources) == 2
    assert manifest.sources[0].item_id == "p001"
    assert manifest.sources[1].item_id == "p002"


def test_ingestion_and_provenance_roundtrip(tmp_path):
    manifest = _fixture(tmp_path)
    original = load_catalog()
    prepared = prepare_image_batch(manifest, original)
    assert len(original.media) == 0
    assert len(prepared.catalog.media) == 2
    target = write_image_batch(prepared, tmp_path / "export")
    restored = load_catalog(target / "catalog.json")
    assert restored.media == prepared.catalog.media
    report = json.loads((target / "provenance.json").read_text())
    assert len(report["assets"]) == 2
    for record in report["assets"]:
        assert record["rights_basis"] == "owned"
        asset = target / "assets" / f"{record['media_id']}.png"
        assert hashlib.sha256(asset.read_bytes()).hexdigest() == record["png_sha256"]
        with Image.open(asset) as img:
            assert img.mode == "RGB"
            assert img.size == (record["width"], record["height"])
    assert target.joinpath("assets/image_p001.png").is_file()


def test_unchanged_inputs_produce_same_hashes(tmp_path):
    path = _fixture(tmp_path)
    a = prepare_image_batch(path, load_catalog())
    b = prepare_image_batch(path, load_catalog())
    assert [(x.input_sha256, x.normalized_sha256) for x in a.images] == [
        (x.input_sha256, x.normalized_sha256) for x in b.images
    ]


def test_no_overwrite(tmp_path):
    prepared = prepare_image_batch(_fixture(tmp_path), load_catalog())
    target = tmp_path / "export"
    write_image_batch(prepared, target)
    with pytest.raises(MediaIngestionError, match="exists"):
        write_image_batch(prepared, target)
    assert (target / "catalog.json").is_file()


@pytest.mark.parametrize("change,match", [
    (lambda m: m.update(schema_version=2), "schema_version"),
    (lambda m: m["dataset"].update(synthetic=False), "synthetic"),
    (lambda m: m["assets"][0].update(item_id="missing"), "missing item"),
    (lambda m: m["assets"][0].update(media_id="../bad"), "media_id"),
    (lambda m: m["assets"][1].update(media_id="image_p001"), "duplicate"),
    (lambda m: m["assets"][0].update(rights_basis="unknown"), "rights_basis"),
    (lambda m: m["assets"][0].pop("license"), "missing"),
    (lambda m: m["assets"][0].update(license=""), "license"),
    (lambda m: m["assets"][0].update(path="../outside.png"), "relative"),
    (lambda m: m["assets"][0].update(path="/tmp/outside.png"), "relative"),
    (lambda m: m["assets"][0].update(path="C:\\temp\\image.png"), "relative"),
    (lambda m: m["assets"].append(m["assets"][0]), "duplicate"),
    (lambda m: m.update(unexpected=True), "unknown"),
])
def test_invalid_manifest(tmp_path, change, match):
    path = _fixture(tmp_path)
    _modify(path, change)
    with pytest.raises(MediaIngestionError, match=match):
        prepare_image_batch(path, load_catalog())


def test_existing_catalog_media_rejected(tmp_path):
    path = _fixture(tmp_path)
    catalog = prepare_image_batch(path, load_catalog()).catalog
    with pytest.raises(MediaIngestionError, match="without media"):
        prepare_image_batch(path, catalog)


def test_content_duplicate_detected(tmp_path):
    path = _fixture(tmp_path)
    source = tmp_path / "media/orange-noodles.png"
    (tmp_path / "media/mushroom-pasta.png").write_bytes(source.read_bytes())
    with pytest.raises(MediaIngestionError, match="duplicate image content"):
        prepare_image_batch(path, load_catalog())


def test_symlink_escape_rejected(tmp_path):
    path = _fixture(tmp_path)
    external = tmp_path.parent / f"{tmp_path.name}-outside.png"
    external.write_bytes((SAMPLE / "media/orange-noodles.png").read_bytes())
    (tmp_path / "media/shortcut.png").symlink_to(external)
    _modify(path, lambda m: m["assets"][0].update(path="media/shortcut.png"))
    try:
        with pytest.raises(MediaIngestionError, match="escapes"):
            prepare_image_batch(path, load_catalog())
    finally:
        external.unlink()


def test_invalid_bytes_rejected_without_partial_output(tmp_path):
    path = _fixture(tmp_path)
    (tmp_path / "media/orange-noodles.png").write_bytes(b"not an image")
    with pytest.raises(MediaIngestionError, match="cannot decode"):
        prepare_image_batch(path, load_catalog())
    assert not (tmp_path / "export").exists()


def test_max_input_size(tmp_path):
    path = _fixture(tmp_path)
    f = tmp_path / "media/orange-noodles.png"
    with f.open("wb") as handle:
        handle.truncate(16 * 1024 * 1024)
    with pytest.raises(MediaIngestionError, match="15 MiB"):
        prepare_image_batch(path, load_catalog())


def test_non_png_input_normalized(tmp_path):
    path = _fixture(tmp_path)
    source = tmp_path / "media/orange-noodles.jpg"
    with Image.open(tmp_path / "media/orange-noodles.png") as image:
        image.save(source, format="JPEG")
    _modify(path, lambda m: m["assets"][0].update(path="media/orange-noodles.jpg"))
    batch = prepare_image_batch(path, load_catalog())
    assert batch.images[0].input_format == "JPEG"
    assert batch.images[0].data.startswith(b"\x89PNG\r\n\x1a\n")


def test_png_strips_attached_metadata(tmp_path):
    path = _fixture(tmp_path)
    source = tmp_path / "media/orange-noodles.png"
    with Image.open(source) as image:
        from PIL import PngImagePlugin
        info = PngImagePlugin.PngInfo()
        info.add_text("Sensitive", "private EXIF-like note")
        image.save(source, format="PNG", pnginfo=info)
    batch = prepare_image_batch(path, load_catalog())
    assert b"Sensitive" not in batch.images[0].data
    assert b"private EXIF-like note" not in batch.images[0].data


def test_animated_gif_rejected(tmp_path):
    path = _fixture(tmp_path)
    source = tmp_path / "media/animated.gif"
    a = Image.new("RGB", (10, 10), "red")
    b = Image.new("RGB", (10, 10), "blue")
    a.save(source, save_all=True, append_images=[b], duration=50, loop=0)
    _modify(path, lambda m: m["assets"][0].update(path="media/animated.gif"))
    with pytest.raises(MediaIngestionError, match="cannot decode"):
        prepare_image_batch(path, load_catalog())


def test_parent_directory_created(tmp_path):
    batch = prepare_image_batch(_fixture(tmp_path), load_catalog())
    target = tmp_path / "deep" / "nested" / "export"
    assert write_image_batch(batch, target) == target


def test_invalid_catalog_id_in_manifest(tmp_path):
    path = _fixture(tmp_path)
    _modify(path, lambda m: m["assets"][0].update(media_id="not/valid"))
    with pytest.raises(MediaIngestionError, match="media_id"):
        prepare_image_batch(path, load_catalog())


def test_malformed_catalog_has_no_output(tmp_path):
    path = _fixture(tmp_path)
    catalog = replace(load_catalog(), synthetic=False)
    with pytest.raises(MediaIngestionError):
        prepare_image_batch(path, catalog)


def test_transparent_image_composited_on_white(tmp_path):
    path = _fixture(tmp_path)
    source = tmp_path / "media/transparent.png"
    Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(source)
    _modify(path, lambda m: m["assets"][0].update(path="media/transparent.png"))
    prepared = prepare_image_batch(path, load_catalog())
    from io import BytesIO
    with Image.open(BytesIO(prepared.images[0].data)) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_missing_image_rejected(tmp_path):
    path = _fixture(tmp_path)
    _modify(path, lambda m: m["assets"][0].update(path="media/missing.png"))
    with pytest.raises(MediaIngestionError, match="cannot be resolved"):
        prepare_image_batch(path, load_catalog())
