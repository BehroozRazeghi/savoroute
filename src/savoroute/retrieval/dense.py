"""Persistent SQLite vectors with optional FAISS HNSW acceleration.

The JSON vector index remains the exact reference. SQLite keeps stable record
identities, source hashes and packed float32 vectors. FAISS is optional and the
binary index is read only from locally created, digest-validated bundles.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import struct
import tempfile
from collections.abc import Iterable, Sequence
from contextlib import closing
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from savoroute.domain.models import Catalog
from savoroute.retrieval.vector import (
    VectorHit,
    VectorIndex,
    VectorIndexError,
    VectorRecord,
    catalog_fingerprint,
    local_image_path,
    normalized_vector,
)

_ENGINE = Literal["sqlite", "faiss-hnsw"]
_SCHEMA = 1
_MAX_RECORDS = 2_000_000
_MAX_BUNDLE_BYTES = 10 * 1024**3


class DenseIndexError(VectorIndexError):
    """Invalid persistent vector bundle or missing optional ANN dependency."""


@dataclass(frozen=True, slots=True)
class DenseIndex:
    root: Path
    engine: _ENGINE
    model_id: str
    embedding_space_id: str
    dimension: int
    dataset_name: str
    synthetic: bool
    catalog_sha256: str
    count: int
    hnsw_m: int = 0
    ef_search: int = 0


def _digest_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    # immutable avoids creating -wal and -shm sidecars during queries.
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)


def _encode(vector: Sequence[float], dimension: int) -> bytes:
    normalized = normalized_vector(vector, dimension=dimension)
    return struct.pack(f"<{dimension}f", *normalized)


def _decode(blob: bytes, dimension: int) -> tuple[float, ...]:
    if len(blob) != dimension * 4:
        raise DenseIndexError("stored vector has an invalid byte length")
    values = struct.unpack(f"<{dimension}f", blob)
    if not all(math.isfinite(v) for v in values):
        raise DenseIndexError("stored vector contains nonfinite values")
    return values


@lru_cache(maxsize=2)
def _ann_cache(path: str):
    """Read a previously integrity-checked, immutable local index once per process."""
    faiss, _ = _faiss()
    return faiss.read_index(path)


def _faiss():
    try:
        import faiss
        import numpy as np
    except ImportError as exc:
        raise DenseIndexError(
            "FAISS backend requires: python -m pip install -e '.[ann]'"
        ) from exc
    return faiss, np


def write_dense_index(
    records: Iterable[VectorRecord], output_dir: str | Path, *,
    model_id: str, embedding_space_id: str, dimension: int,
    dataset_name: str, synthetic: bool, catalog_sha256: str,
    engine: _ENGINE = "sqlite", hnsw_m: int = 24,
    ef_construction: int = 120, ef_search: int = 96,
    batch_size: int = 512,
) -> DenseIndex:
    """Write a new immutable bundle from record IDs in strictly increasing order.

    The iterable may be streamed from a larger dataset; no JSON export is
    required. A temporary directory is published only after all files succeed.
    """
    target = Path(output_dir).resolve()
    if target.exists():
        raise DenseIndexError(f"output already exists: {target}")
    if engine not in ("sqlite", "faiss-hnsw"):
        raise DenseIndexError("engine must be sqlite or faiss-hnsw")
    if (type(dimension) is not int or not 1 <= dimension <= 4096
            or any(not isinstance(x, str) or not x.strip()
                   for x in (model_id, embedding_space_id, dataset_name))
            or type(synthetic) is not bool or len(catalog_sha256) != 64
            or any(c not in "0123456789abcdef" for c in catalog_sha256)):
        raise DenseIndexError("invalid model or dataset metadata")
    if (type(batch_size) is not int or batch_size < 1 or batch_size > 100_000
            or type(hnsw_m) is not int or not 4 <= hnsw_m <= 64
            or type(ef_construction) is not int or not 16 <= ef_construction <= 2000
            or type(ef_search) is not int or not 1 <= ef_search <= 10_000):
        raise DenseIndexError("invalid index build parameters")
    faiss = np = None
    ann = None
    if engine == "faiss-hnsw":
        faiss, np = _faiss()
        ann = faiss.IndexHNSWFlat(dimension, hnsw_m, faiss.METRIC_INNER_PRODUCT)
        ann.hnsw.efConstruction = ef_construction
        ann.hnsw.efSearch = ef_search
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".savoroute-dense-", dir=target.parent) as tmp:
        root = Path(tmp)
        database = root / "vectors.sqlite"
        conn = sqlite3.connect(database)
        previous = ""
        count = 0
        try:
            conn.executescript("""
                CREATE TABLE records (
                    ordinal INTEGER PRIMARY KEY,
                    record_id TEXT NOT NULL UNIQUE,
                    item_id TEXT NOT NULL,
                    modality TEXT NOT NULL CHECK (modality IN ('text', 'image')),
                    input_sha256 TEXT NOT NULL,
                    vector BLOB NOT NULL
                );
                CREATE INDEX records_modality ON records(modality, item_id);
            """)
            batch: list[tuple[int, str, str, str, str, bytes]] = []
            ann_batch: list[tuple[float, ...]] = []

            def flush() -> None:
                if batch:
                    conn.executemany("INSERT INTO records VALUES (?,?,?,?,?,?)", batch)
                    batch.clear()
                if ann_batch:
                    assert ann is not None and np is not None
                    ann.add(np.asarray(ann_batch, dtype="float32"))
                    ann_batch.clear()

            for record in records:
                if count >= _MAX_RECORDS:
                    raise DenseIndexError("persistent index exceeds record limit")
                if (not isinstance(record, VectorRecord)
                        or record.modality not in ("text", "image")
                        or not record.record_id.startswith(record.modality + ":")
                        or record.record_id <= previous or not record.item_id
                        or len(record.input_sha256) != 64
                        or any(c not in "0123456789abcdef" for c in record.input_sha256)):
                    raise DenseIndexError("records must have valid, strictly increasing IDs")
                blob = _encode(record.vector, dimension)
                batch.append((count, record.record_id, record.item_id,
                              record.modality, record.input_sha256, blob))
                if ann is not None:
                    ann_batch.append(_decode(blob, dimension))
                previous = record.record_id
                count += 1
                if len(batch) >= batch_size:
                    flush()
            flush()
            if count == 0:
                raise DenseIndexError("cannot publish an empty index")
            conn.commit()
        finally:
            conn.close()
        files = {"vectors.sqlite": _digest_file(database)}
        if ann is not None:
            assert faiss is not None
            faiss.write_index(ann, str(root / "hnsw.faiss"))
            files["hnsw.faiss"] = _digest_file(root / "hnsw.faiss")
        metadata = {
            "schema_version": _SCHEMA,
            "engine": engine,
            "model_id": model_id,
            "embedding_space_id": embedding_space_id,
            "dimension": dimension,
            "dataset_name": dataset_name,
            "synthetic": synthetic,
            "catalog_sha256": catalog_sha256,
            "count": count,
            "hnsw_m": hnsw_m if ann is not None else 0,
            "ef_search": ef_search if ann is not None else 0,
            "files": files,
        }
        (root / "manifest.json").write_text(
            json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        root.rename(target)
    return load_dense_index(target)


def convert_vector_index(
    index: VectorIndex, output_dir: str | Path, *,
    engine: _ENGINE = "sqlite", hnsw_m: int = 24,
    ef_construction: int = 120, ef_search: int = 96,
) -> DenseIndex:
    """Convert the portable JSON reference into a persistent backend."""
    return write_dense_index(
        sorted(index.records, key=lambda r: r.record_id), output_dir,
        model_id=index.model_id, embedding_space_id=index.embedding_space_id,
        dimension=index.dimension, dataset_name=index.dataset_name,
        synthetic=index.synthetic, catalog_sha256=index.catalog_sha256,
        engine=engine, hnsw_m=hnsw_m,
        ef_construction=ef_construction, ef_search=ef_search,
    )


def load_dense_index(directory: str | Path) -> DenseIndex:
    root = Path(directory).resolve()
    path = root / "manifest.json"
    if path.stat().st_size > 8192:
        raise DenseIndexError("manifest too large")
    meta = json.loads(path.read_text(encoding="utf-8"))
    expected = {"schema_version", "engine", "model_id", "embedding_space_id",
                "dimension", "dataset_name", "synthetic", "catalog_sha256",
                "count", "hnsw_m", "ef_search", "files"}
    if not isinstance(meta, dict) or set(meta) != expected or (type(meta["schema_version"]) is not int or meta["schema_version"] != _SCHEMA):
        raise DenseIndexError("unsupported bundle manifest")
    if (meta["engine"] not in ("sqlite", "faiss-hnsw")
            or type(meta["dimension"]) is not int or not 1 <= meta["dimension"] <= 4096
            or type(meta["count"]) is not int or not 1 <= meta["count"] <= _MAX_RECORDS
            or type(meta["synthetic"]) is not bool
            or any(not isinstance(meta[field], str) or not meta[field].strip()
                   for field in ("model_id", "embedding_space_id", "dataset_name"))
            or not isinstance(meta["catalog_sha256"], str)
            or len(meta["catalog_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in meta["catalog_sha256"]) ):
        raise DenseIndexError("invalid bundle metadata")
    file_names = ("vectors.sqlite",) if meta["engine"] == "sqlite" else (
        "vectors.sqlite", "hnsw.faiss"
    )
    if (not isinstance(meta["files"], dict)
            or set(meta["files"]) != set(file_names)):
        raise DenseIndexError("invalid bundle files")
    for name in file_names:
        file = root / name
        if (file.is_symlink() or not file.is_file()
                or not 0 < file.stat().st_size < _MAX_BUNDLE_BYTES
                or _digest_file(file) != meta["files"][name]):
            raise DenseIndexError(f"bundle file is missing or altered: {name}")
    with closing(_connect(root / "vectors.sqlite")) as conn:
        total, min_id, max_id = conn.execute(
            "SELECT count(*), min(ordinal), max(ordinal) FROM records"
        ).fetchone()
    if total != meta["count"] or min_id != 0 or max_id != total - 1:
        raise DenseIndexError("bundle record count or ordinals do not match")
    if meta["engine"] == "sqlite" and (meta["hnsw_m"] != 0 or meta["ef_search"] != 0):
        raise DenseIndexError("unexpected HNSW parameters in SQLite bundle")
    if meta["engine"] == "faiss-hnsw" and (
        type(meta["hnsw_m"]) is not int or not 4 <= meta["hnsw_m"] <= 64
        or type(meta["ef_search"]) is not int or not 1 <= meta["ef_search"] <= 10_000
    ):
        raise DenseIndexError("invalid HNSW parameters")
    return DenseIndex(
        root, meta["engine"], meta["model_id"], meta["embedding_space_id"],
        meta["dimension"], meta["dataset_name"], meta["synthetic"],
        meta["catalog_sha256"], meta["count"],
        meta["hnsw_m"], meta["ef_search"],
    )


def validate_dense_catalog(
    index: DenseIndex, catalog: Catalog, *, catalog_dir: Path | None = None,
) -> None:
    if index.catalog_sha256 != catalog_fingerprint(catalog):
        raise DenseIndexError("catalog differs from the version used to build this index")
    if catalog_dir is None:
        return
    media = {m.media_id: m for m in catalog.media}
    with closing(_connect(index.root / "vectors.sqlite")) as conn:
        for record_id, expected in conn.execute(
            "SELECT record_id, input_sha256 FROM records WHERE modality = 'image'"
        ):
            record = media.get(record_id.removeprefix("image:"))
            if record is None:
                raise DenseIndexError("index contains unknown media ID")
            path = local_image_path(catalog_dir, record.uri)
            if _digest_file(path) != expected:
                raise DenseIndexError(f"image content changed since indexing: {record.media_id}")


def search_dense(
    index: DenseIndex, query_vector: Sequence[float], *,
    target: Literal["text", "image", "all"] = "all", k: int = 5,
    catalog: Catalog | None = None,
    kind: Literal["restaurant", "recipe"] | None = None,
    exclude: frozenset[str] = frozenset(), unique_items: bool = False,
    allowed_item_ids: frozenset[str] | None = None,
) -> tuple[VectorHit, ...]:
    """Exact SQLite scan or approximate FAISS HNSW; hard filters after retrieval."""
    if target not in ("text", "image", "all") or type(k) is not int or not 1 <= k <= 1000:
        raise DenseIndexError("invalid search target or k")
    if kind not in (None, "restaurant", "recipe") or (kind is not None and catalog is None):
        raise DenseIndexError("kind requires a matching catalog")
    if catalog is not None:
        validate_dense_catalog(index, catalog)
    item_kind = {item.item_id: item.kind for item in catalog.items} if catalog else {}
    query = normalized_vector(query_vector, dimension=index.dimension)
    hits: list[VectorHit] = []
    if index.engine == "sqlite":
        sql = "SELECT record_id, item_id, modality, vector FROM records"
        if target != "all":
            sql += " WHERE modality = ?"
        with closing(_connect(index.root / "vectors.sqlite")) as conn:
            for record_id, item_id, modality, blob in conn.execute(
                sql, () if target == "all" else (target,)
            ):
                if (record_id in exclude or (allowed_item_ids is not None
                        and item_id not in allowed_item_ids)
                        or (kind is not None and item_kind[item_id] != kind)):
                    continue
                vec = _decode(blob, index.dimension)
                score = math.fsum(a * b for a, b in zip(query, vec, strict=True))
                hits.append(VectorHit(record_id, item_id, modality,
                                      max(-1.0, min(1.0, score))))
    else:
        _, np = _faiss()
        # FAISS serializations are not safe for untrusted input. The manifest
        # hash is verified at load; open only bundles built locally/trusted.
        ann = _ann_cache(str(index.root / "hnsw.faiss"))
        if ann.ntotal != index.count or ann.d != index.dimension:
            raise DenseIndexError("HNSW index dimensions/count mismatch")
        ann.hnsw.efSearch = index.ef_search
        wanted = min(index.count, max(k * 4, 32))
        with closing(_connect(index.root / "vectors.sqlite")) as conn:
            while True:
                values, ordinals = ann.search(
                    np.asarray([query], dtype="float32"), wanted
                )
                choices = [(int(position), float(value)) for position, value in
                           zip(ordinals[0], values[0], strict=True) if position >= 0]
                mapping = {}
                for start in range(0, len(choices), 500):
                    portion = choices[start:start + 500]
                    labels = [position for position, _ in portion]
                    clause = ",".join("?" for _ in labels)
                    mapping.update({r[0]: r[1:] for r in conn.execute(
                        f"SELECT ordinal, record_id, item_id, modality FROM records "
                        f"WHERE ordinal IN ({clause})", labels
                    )})
                hits = []
                for position, value in choices:
                    if position not in mapping:
                        raise DenseIndexError("ANN labels do not match metadata")
                    record_id, item_id, modality = mapping[position]
                    if (record_id in exclude or target not in ("all", modality)
                            or (allowed_item_ids is not None and item_id not in allowed_item_ids)
                            or (kind is not None and item_kind[item_id] != kind)):
                        continue
                    hits.append(VectorHit(record_id, item_id, modality,
                                          max(-1.0, min(1.0, value))))
                if wanted == index.count or len({h.item_id for h in hits}) >= k:
                    break
                wanted = min(index.count, wanted * 2)
    hits.sort(key=lambda h: (-h.score, h.record_id))
    if unique_items:
        seen: set[str] = set()
        unique = []
        for hit in hits:
            if hit.item_id not in seen:
                unique.append(hit)
                seen.add(hit.item_id)
        hits = unique
    return tuple(hits[:k])


def dense_modalities(index: DenseIndex) -> frozenset[str]:
    """Read available modalities without loading vectors into Python memory."""
    with closing(_connect(index.root / "vectors.sqlite")) as conn:
        return frozenset(row[0] for row in conn.execute(
            "SELECT DISTINCT modality FROM records"
        ))
