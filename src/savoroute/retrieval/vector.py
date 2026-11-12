"""Exact cosine search over a portable, versioned joint text/image index.

The JSON index is intended for small catalogs and evaluation, not approximate
nearest-neighbor search at production scale. No network access occurs here.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from savoroute.data.catalog import catalog_to_dict
from savoroute.domain.models import Catalog, CatalogItem
from savoroute.providers.contracts import JointTextImageEmbedder
from savoroute.services.storage import write_json_file

Modality = Literal["text", "image"]
_MAX_INDEX_BYTES = 64 * 1024 * 1024
_MAX_RECORDS = 20_000
_MAX_DIMENSION = 4096
_MAX_IMAGE_BYTES = 20 * 1024 * 1024


class VectorIndexError(ValueError):
    """Invalid index, incompatible encoder, or unsupported local source."""


@dataclass(frozen=True, slots=True)
class VectorRecord:
    record_id: str
    item_id: str
    modality: Modality
    input_sha256: str
    vector: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class VectorIndex:
    model_id: str
    embedding_space_id: str
    dimension: int
    dataset_name: str
    synthetic: bool
    catalog_sha256: str
    records: tuple[VectorRecord, ...]


@dataclass(frozen=True, slots=True)
class VectorHit:
    record_id: str
    item_id: str
    modality: Modality
    score: float

    def as_dict(self) -> dict[str, str | float]:
        return {"record_id": self.record_id, "item_id": self.item_id,
                "modality": self.modality, "score": round(self.score, 6)}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def catalog_fingerprint(catalog: Catalog) -> str:
    payload = json.dumps(catalog_to_dict(catalog), sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
    return _sha256(payload)


def item_text(item: CatalogItem) -> str:
    """Deterministic, explicitly specified text representation for embedding."""
    parts = [item.title, item.description]
    for name, values in (("Cuisine", item.cuisines), ("Dietary", item.dietary_tags),
                         ("Ingredients", item.ingredients)):
        if values:
            parts.append(f"{name}: {', '.join(values)}")
    if item.location:
        parts.append(f"Location: {item.location}")
    return "\n".join(parts)


def local_image_path(catalog_dir: Path, uri: str) -> Path:
    """Resolve only an in-catalog relative asset path; reject symlink escapes."""
    rel = PurePosixPath(uri)
    if (not uri or rel.is_absolute() or ".." in rel.parts or "\\" in uri
            or ":" in uri or uri.startswith("~")):
        raise VectorIndexError(f"image uri must be a relative local path: {uri!r}")
    root = catalog_dir.resolve()
    path = (root / uri).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise VectorIndexError(f"image path escapes catalog directory: {uri!r}")
    if path.stat().st_size > _MAX_IMAGE_BYTES:
        raise VectorIndexError("indexed image exceeds 20 MiB")
    return path


def _unit(values: Sequence[float], *, dimension: int | None = None) -> tuple[float, ...]:
    if (not isinstance(values, (list, tuple)) or not values
            or len(values) > _MAX_DIMENSION or (dimension is not None and len(values) != dimension)):
        raise VectorIndexError("invalid embedding dimension")
    if any(type(x) not in (float, int) or not math.isfinite(x) for x in values):
        raise VectorIndexError("embedding values must be finite numbers")
    norm = math.hypot(*values)
    if not math.isfinite(norm) or norm <= 1e-12:
        raise VectorIndexError("embedding must have nonzero finite norm")
    return tuple(float(v / norm) for v in values)


def normalized_vector(values: Sequence[float], *, dimension: int | None = None) -> tuple[float, ...]:
    """Validate and L2-normalize a vector for shared-space cosine retrieval."""
    return _unit(values, dimension=dimension)


def _validate_encoder(encoder: JointTextImageEmbedder) -> None:
    if (not isinstance(encoder.model_id, str) or not encoder.model_id.strip()
            or not isinstance(encoder.embedding_space_id, str)
            or not encoder.embedding_space_id.strip()):
        raise VectorIndexError("encoder must declare a model and embedding space")


def build_vector_index(
    catalog: Catalog, catalog_dir: Path, encoder: JointTextImageEmbedder, *,
    include_text: bool = True, include_images: bool = True,
) -> VectorIndex:
    """Embed catalog items and local images using a shared model-defined space."""
    _validate_encoder(encoder)
    if not include_text and not include_images:
        raise VectorIndexError("at least one modality must be enabled")
    if (len(catalog.items) if include_text else 0) + (
            len(catalog.media) if include_images else 0) > _MAX_RECORDS:
        raise VectorIndexError("catalog is too large for the JSON vector index")
    items = sorted(catalog.items, key=lambda x: x.item_id) if include_text else []
    images = sorted(catalog.media, key=lambda x: x.media_id) if include_images else []
    paths = [local_image_path(catalog_dir, media.uri) for media in images]
    inputs = [item_text(item) for item in items]
    text_vectors = encoder.embed_texts(inputs) if items else []
    image_vectors = encoder.embed_images(paths) if images else []
    if len(text_vectors) != len(items) or len(image_vectors) != len(images):
        raise VectorIndexError("encoder returned an unexpected number of vectors")
    dimensions: set[int] = set()
    records: list[VectorRecord] = []
    for item, text, values in zip(items, inputs, text_vectors, strict=True):
        vector = _unit(values)
        dimensions.add(len(vector))
        records.append(VectorRecord(f"text:{item.item_id}", item.item_id, "text",
                                    _sha256(text.encode("utf-8")), vector))
    for media, path, values in zip(images, paths, image_vectors, strict=True):
        vector = _unit(values)
        dimensions.add(len(vector))
        records.append(VectorRecord(f"image:{media.media_id}", media.item_id, "image",
                                    _sha256(path.read_bytes()), vector))
    if len(dimensions) != 1:
        raise VectorIndexError("encoder emitted inconsistent cross-modal dimensions")
    if not records:
        raise VectorIndexError("no records available for indexing")
    return VectorIndex(encoder.model_id, encoder.embedding_space_id, dimensions.pop(),
                       catalog.dataset_name, catalog.synthetic, catalog_fingerprint(catalog),
                       tuple(records))


def index_to_dict(index: VectorIndex) -> dict[str, Any]:
    return {"schema_version": 1, "model": {"id": index.model_id,
            "embedding_space_id": index.embedding_space_id, "dimension": index.dimension},
            "dataset": {"name": index.dataset_name, "synthetic": index.synthetic,
                        "catalog_sha256": index.catalog_sha256},
            "records": [dict(record_id=r.record_id, item_id=r.item_id,
                             modality=r.modality, input_sha256=r.input_sha256,
                             vector=list(r.vector)) for r in index.records]}


def _keys(data: Any, expected: set[str], context: str) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != expected:
        raise VectorIndexError(f"invalid {context} object or keys")
    return data


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def parse_vector_index(payload: Any) -> VectorIndex:
    doc = _keys(payload, {"schema_version", "model", "dataset", "records"}, "index")
    if type(doc["schema_version"]) is not int or doc["schema_version"] != 1:
        raise VectorIndexError("unsupported vector index schema")
    model = _keys(doc["model"], {"id", "embedding_space_id", "dimension"}, "model")
    data = _keys(doc["dataset"], {"name", "synthetic", "catalog_sha256"}, "dataset")
    dimension = model["dimension"]
    if type(dimension) is not int or not 1 <= dimension <= _MAX_DIMENSION:
        raise VectorIndexError("invalid vector dimension")
    if any(not isinstance(model[field], str) or not model[field].strip()
           for field in ("id", "embedding_space_id")):
        raise VectorIndexError("invalid model identity")
    if (not isinstance(data["name"], str) or not data["name"].strip()
            or type(data["synthetic"]) is not bool or not _digest(data["catalog_sha256"])):
        raise VectorIndexError("invalid dataset fingerprint")
    rows = doc["records"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_RECORDS:
        raise VectorIndexError("invalid record count")
    seen: set[str] = set()
    records = []
    for row in rows:
        row = _keys(row, {"record_id", "item_id", "modality", "input_sha256", "vector"},
                    "vector record")
        identifier, item_id, modality = row["record_id"], row["item_id"], row["modality"]
        if (not isinstance(item_id, str) or not item_id or modality not in ("text", "image")
                or not isinstance(identifier, str) or identifier in seen
                or not identifier.startswith(f"{modality}:") or len(identifier) > 90
                or not _digest(row["input_sha256"])):
            raise VectorIndexError("invalid or duplicate vector record identity")
        vector = _unit(row["vector"], dimension=dimension)
        if abs(math.hypot(*row["vector"]) - 1.0) > 1e-3:
            raise VectorIndexError("stored vectors must be unit-normalized")
        seen.add(identifier)
        records.append(VectorRecord(identifier, item_id, modality, row["input_sha256"],
                                    vector))
    return VectorIndex(model["id"], model["embedding_space_id"], dimension,
                       data["name"], data["synthetic"], data["catalog_sha256"],
                       tuple(records))


def write_vector_index(index: VectorIndex, path: str | Path) -> None:
    # Validate serialization before publishing. Existing files are never overwritten.
    payload = index_to_dict(index)
    parse_vector_index(payload)
    write_json_file(payload, path)


def load_vector_index(path: str | Path) -> VectorIndex:
    target = Path(path)
    if target.stat().st_size > _MAX_INDEX_BYTES:
        raise VectorIndexError("vector index exceeds 64 MiB")
    return parse_vector_index(json.loads(target.read_text(encoding="utf-8")))


def validate_catalog(
    index: VectorIndex, catalog: Catalog, *, catalog_dir: Path | None = None,
) -> None:
    if index.catalog_sha256 != catalog_fingerprint(catalog):
        raise VectorIndexError("catalog differs from the version used to build this index")
    item_ids = {item.item_id for item in catalog.items}
    media_by_id = {asset.media_id: asset.item_id for asset in catalog.media}
    for record in index.records:
        if record.item_id not in item_ids:
            raise VectorIndexError("vector record references an unknown item")
        if record.modality == "text":
            if record.record_id != f"text:{record.item_id}":
                raise VectorIndexError("text record identity mismatch")
        else:
            media_id = record.record_id.removeprefix("image:")
            if media_by_id.get(media_id) != record.item_id:
                raise VectorIndexError("image record identity mismatch")
            if catalog_dir is not None:
                media = next(asset for asset in catalog.media if asset.media_id == media_id)
                path = local_image_path(catalog_dir, media.uri)
                if _sha256(path.read_bytes()) != record.input_sha256:
                    raise VectorIndexError(f"image content changed since indexing: {media_id}")


def search_vectors(
    index: VectorIndex, query_vector: Sequence[float], *,
    target: Literal["text", "image", "all"] = "all", k: int = 5,
    catalog: Catalog | None = None, kind: Literal["restaurant", "recipe"] | None = None,
    exclude: frozenset[str] = frozenset(), unique_items: bool = False,
) -> tuple[VectorHit, ...]:
    """Exact cosine search; stable ties, hard filters, optional item-level max pooling."""
    if target not in ("text", "image", "all") or type(k) is not int or not 1 <= k <= 1000:
        raise VectorIndexError("invalid search target or k")
    if kind not in (None, "restaurant", "recipe"):
        raise VectorIndexError("invalid kind")
    if kind is not None and catalog is None:
        raise VectorIndexError("kind filtering requires a matching catalog")
    if catalog is not None:
        validate_catalog(index, catalog)
    _items = {item.item_id: item for item in catalog.items} if catalog else {}
    query = _unit(query_vector, dimension=index.dimension)
    ranked = []
    for row in index.records:
        if row.record_id in exclude or target not in ("all", row.modality):
            continue
        if kind and _items[row.item_id].kind != kind:
            continue
        score = sum(a * b for a, b in zip(query, row.vector, strict=True))
        ranked.append(VectorHit(row.record_id, row.item_id, row.modality,
                                max(-1.0, min(1.0, score))))
    ranked.sort(key=lambda hit: (-hit.score, hit.record_id))
    if unique_items:
        seen: set[str] = set()
        unique = []
        for hit in ranked:
            if hit.item_id not in seen:
                unique.append(hit)
                seen.add(hit.item_id)
        ranked = unique
    return tuple(ranked[:k])


def search_with_encoder(index: VectorIndex, encoder: JointTextImageEmbedder, *,
                        text: str | None = None, image: Path | None = None,
                        target: Literal["text", "image", "all"] = "all", k: int = 5,
                        catalog: Catalog | None = None,
                        kind: Literal["restaurant", "recipe"] | None = None,
                        exclude: frozenset[str] = frozenset(),
                        unique_items: bool = False) -> tuple[VectorHit, ...]:
    if (text is None) == (image is None):
        raise VectorIndexError("provide exactly one text or image query")
    _validate_encoder(encoder)
    if encoder.embedding_space_id != index.embedding_space_id or encoder.model_id != index.model_id:
        raise VectorIndexError("query encoder does not match the index model identity")
    result = encoder.embed_texts([text]) if text is not None else encoder.embed_images([image])
    if len(result) != 1:
        raise VectorIndexError("query encoder returned an unexpected number of vectors")
    return search_vectors(index, result[0], target=target, k=k, catalog=catalog,
                          kind=kind, exclude=exclude, unique_items=unique_items)
