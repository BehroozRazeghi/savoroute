"""Validate local image sources and stage a self-contained catalog export.

The manifest references local files only. No network fetch or rights verification
is performed. A new output directory is published after successful preparation.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from savoroute.data.catalog import catalog_to_dict, parse_catalog
from savoroute.domain.models import Catalog, MediaAsset

_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_MAX_ASSETS = 64
_MAX_INPUT_BYTES = 15 * 1024 * 1024
_MAX_TOTAL_OUTPUT_BYTES = 64 * 1024 * 1024
_MAX_MANIFEST_BYTES = 128 * 1024
_MAX_PIXELS = 24_000_000
_MAX_SIDE = 1280
_FORMATS = ("PNG", "JPEG", "WEBP")


class MediaIngestionError(ValueError):
    """An invalid image, manifest, or image export operation."""


@dataclass(frozen=True, slots=True)
class ImageSource:
    media_id: str
    item_id: str
    path: str
    source: str
    rights_basis: str
    license: str
    attribution: str
    caption: str | None


@dataclass(frozen=True, slots=True)
class ImageManifest:
    name: str
    synthetic: bool
    sources: tuple[ImageSource, ...]


@dataclass(frozen=True, slots=True)
class PreparedImage:
    record: ImageSource
    data: bytes
    input_sha256: str
    normalized_sha256: str
    width: int
    height: int
    input_format: str


@dataclass(frozen=True, slots=True)
class ImageBatch:
    catalog: Catalog
    images: tuple[PreparedImage, ...]
    manifest_name: str


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MediaIngestionError(f"{context} must be an object")
    return value


def _keys(value: dict[str, Any], required: set[str], allowed: set[str], context: str) -> None:
    missing, extra = required - value.keys(), value.keys() - allowed
    if missing or extra:
        raise MediaIngestionError(
            f"{context}: missing={sorted(missing)}, unknown={sorted(extra)}"
        )


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MediaIngestionError(f"{context} must be a nonempty string")
    return value.strip()


def _relative_path(value: Any, context: str) -> str:
    raw = _string(value, context)
    # Deliberately use POSIX paths for portable manifests on Linux, macOS and Windows.
    path = PurePosixPath(raw)
    if (path.is_absolute() or ".." in path.parts or "." in path.parts
            or "\\" in raw or ":" in raw or not path.parts):
        raise MediaIngestionError(f"{context} must be a relative POSIX path within the manifest directory")
    return raw


def parse_image_manifest(payload: Any, catalog: Catalog) -> ImageManifest:
    """Parse a bounded local-image manifest and validate references to catalog items."""
    doc = _object(payload, "manifest")
    _keys(doc, {"schema_version", "dataset", "assets"},
          {"schema_version", "dataset", "assets"}, "manifest")
    if type(doc["schema_version"]) is not int or doc["schema_version"] != 1:
        raise MediaIngestionError("manifest.schema_version must equal 1")
    dataset = _object(doc["dataset"], "manifest.dataset")
    _keys(dataset, {"name", "synthetic"}, {"name", "synthetic"}, "manifest.dataset")
    if type(dataset["synthetic"]) is not bool:
        raise MediaIngestionError("manifest.dataset.synthetic must be a boolean")
    if dataset["synthetic"] != catalog.synthetic:
        raise MediaIngestionError("manifest and catalog must agree on synthetic status")
    if not isinstance(doc["assets"], list) or not 1 <= len(doc["assets"]) <= _MAX_ASSETS:
        raise MediaIngestionError("manifest.assets must contain 1 to 64 images")
    if catalog.media:
        raise MediaIngestionError("this initial batch exporter requires a catalog without media")
    sources: list[ImageSource] = []
    media_ids: set[str] = set()
    for index, entry in enumerate(doc["assets"]):
        context = f"manifest.assets[{index}]"
        row = _object(entry, context)
        required = {"media_id", "item_id", "path", "source", "rights_basis", "license", "attribution"}
        _keys(row, required, required | {"caption"}, context)
        media_id = _string(row["media_id"], f"{context}.media_id")
        item_id = _string(row["item_id"], f"{context}.item_id")
        if not _ID.fullmatch(media_id):
            raise MediaIngestionError(f"{context}.media_id must match {_ID.pattern}")
        if media_id in media_ids:
            raise MediaIngestionError(f"duplicate media_id: {media_id}")
        if catalog.get(item_id) is None:
            raise MediaIngestionError(f"{context}.item_id references missing item: {item_id}")
        if row["rights_basis"] not in ("owned", "licensed", "permission"):
            raise MediaIngestionError(f"{context}.rights_basis must be owned, licensed, or permission")
        caption = row.get("caption")
        if caption is not None:
            caption = _string(caption, f"{context}.caption")
        media_ids.add(media_id)
        sources.append(ImageSource(
            media_id=media_id,
            item_id=item_id,
            path=_relative_path(row["path"], f"{context}.path"),
            source=_string(row["source"], f"{context}.source"),
            rights_basis=row["rights_basis"],
            license=_string(row["license"], f"{context}.license"),
            attribution=_string(row["attribution"], f"{context}.attribution"),
            caption=caption,
        ))
    return ImageManifest(_string(dataset["name"], "manifest.dataset.name"),
                         dataset["synthetic"], tuple(sources))


def _image_bytes(source: Path) -> tuple[bytes, int, int, str]:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:
        raise MediaIngestionError("install savoroute[images] for local image processing") from exc
    if not source.is_file() or source.stat().st_size > _MAX_INPUT_BYTES:
        raise MediaIngestionError(f"image missing or exceeds 15 MiB: {source.name}")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source, formats=_FORMATS) as probe:
                if probe.format not in _FORMATS:
                    raise MediaIngestionError("unsupported image format")
                if probe.width * probe.height > _MAX_PIXELS:
                    raise MediaIngestionError("image exceeds 24 megapixels")
                if getattr(probe, "n_frames", 1) != 1:
                    raise MediaIngestionError("animated images are not supported")
                image_format = probe.format
                probe.verify()
            with Image.open(source, formats=_FORMATS) as opened:
                oriented = ImageOps.exif_transpose(opened)
                if "A" in oriented.getbands() or "transparency" in oriented.info:
                    rgba = oriented.convert("RGBA")
                    background = Image.new("RGBA", rgba.size, "white")
                    background.alpha_composite(rgba)
                    image = background.convert("RGB")
                else:
                    image = oriented.convert("RGB")
                image.thumbnail((_MAX_SIDE, _MAX_SIDE), Image.Resampling.LANCZOS)
                width, height = image.size
                output = io.BytesIO()
                image.save(output, format="PNG", optimize=False)
                return output.getvalue(), width, height, image_format
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning, ValueError) as exc:
        raise MediaIngestionError(f"cannot decode image {source.name}: {exc}") from exc


def prepare_image_batch(manifest_path: str | Path, catalog: Catalog) -> ImageBatch:
    """Validate every image and return an in-memory batch; no outputs are written."""
    path = Path(manifest_path)
    if path.stat().st_size > _MAX_MANIFEST_BYTES:
        raise MediaIngestionError("image manifest exceeds 128 KiB")
    manifest = parse_image_manifest(json.loads(path.read_text(encoding="utf-8")), catalog)
    root = path.resolve().parent
    prepared: list[PreparedImage] = []
    digests: set[str] = set()
    assets: list[MediaAsset] = []
    total_output_bytes = 0
    for source in manifest.sources:
        candidate = root / source.path
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise MediaIngestionError(f"image cannot be resolved: {source.path}") from exc
        if not resolved.is_relative_to(root):
            raise MediaIngestionError(f"image path escapes manifest directory: {source.path}")
        if not resolved.is_file() or resolved.stat().st_size > _MAX_INPUT_BYTES:
            raise MediaIngestionError(f"image missing or exceeds 15 MiB: {source.path}")
        input_hash = hashlib.sha256(resolved.read_bytes()).hexdigest()
        data, width, height, image_format = _image_bytes(resolved)
        total_output_bytes += len(data)
        if total_output_bytes > _MAX_TOTAL_OUTPUT_BYTES:
            raise MediaIngestionError("normalized batch exceeds 64 MiB")
        normalized_hash = hashlib.sha256(data).hexdigest()
        if normalized_hash in digests:
            raise MediaIngestionError(f"duplicate image content: {source.media_id}")
        digests.add(normalized_hash)
        prepared.append(PreparedImage(source, data, input_hash, normalized_hash,
                                      width, height, image_format))
        assets.append(MediaAsset(source.media_id, source.item_id, "image",
                                 f"assets/{source.media_id}.png", source.source,
                                 source.caption))
    # Reuse the canonical catalog parser to validate IDs and any future media constraints.
    payload = catalog_to_dict(catalog)
    payload["media"] = [
        {"media_id": asset.media_id, "item_id": asset.item_id, "kind": asset.kind,
         "uri": asset.uri, "source": asset.source, "caption": asset.caption}
        for asset in assets
    ]
    result = parse_catalog(payload)
    return ImageBatch(result, tuple(prepared), manifest.name)


def write_image_batch(batch: ImageBatch, output_dir: str | Path) -> Path:
    """Publish catalog, provenance and PNG files as a new directory.

    The directory does not overwrite an existing path. A crash before rename
    leaves no visible partial output; temporary files are removed on exceptions.
    """
    target = Path(output_dir)
    if target.exists() or target.is_symlink():
        raise MediaIngestionError(f"output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".savoroute-media-", dir=target.parent))
    try:
        (staging / "assets").mkdir()
        provenance: list[dict[str, Any]] = []
        for prepared in batch.images:
            record = prepared.record
            (staging / "assets" / f"{record.media_id}.png").write_bytes(prepared.data)
            provenance.append({
                "media_id": record.media_id, "item_id": record.item_id,
                "original_path": record.path, "source": record.source,
                "rights_basis": record.rights_basis, "license": record.license,
                "attribution": record.attribution,
                "input_format": prepared.input_format,
                "input_sha256": prepared.input_sha256,
                "png_sha256": prepared.normalized_sha256,
                "width": prepared.width, "height": prepared.height,
            })
        (staging / "catalog.json").write_text(
            json.dumps(catalog_to_dict(batch.catalog), indent=2) + "\n", encoding="utf-8"
        )
        (staging / "provenance.json").write_text(
            json.dumps({"schema_version": 1, "manifest": batch.manifest_name,
                        "assets": provenance}, indent=2) + "\n", encoding="utf-8"
        )
        if target.exists() or target.is_symlink():
            raise MediaIngestionError(f"output already exists: {target}")
        os.rename(staging, target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target
