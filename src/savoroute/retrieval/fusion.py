"""Item-level reciprocal-rank fusion of catalog-backed retrieval sources.

BM25 and cosine scores are never mixed directly. Each source supplies a ranked
list of canonical item IDs, and each list contributes a weighted RRF term.
For image search, record hits are collapsed to distinct items *before* pool
truncation, so multiple images of one item cannot occupy multiple ranks.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from savoroute.domain.models import Catalog, CatalogItem
from savoroute.providers.contracts import JointTextImageEmbedder
from savoroute.retrieval.lexical import SearchFilters, filter_catalog, search_catalog
from savoroute.retrieval.vector import (
    VectorIndex,
    VectorIndexError,
    search_vectors,
    validate_catalog,
)

SourceName = Literal["bm25", "text", "image"]


@dataclass(frozen=True, slots=True)
class FusionWeights:
    bm25: float = 1.0
    text: float = 1.0
    image: float = 1.0

    def __post_init__(self) -> None:
        for value in (self.bm25, self.text, self.image):
            if type(value) not in (float, int) or not math.isfinite(value) or value < 0:
                raise ValueError("fusion weights must be finite nonnegative numbers")
        if self.bm25 + self.text + self.image == 0:
            raise ValueError("at least one fusion weight must be positive")

    def for_source(self, name: SourceName) -> float:
        return float(getattr(self, name))


@dataclass(frozen=True, slots=True)
class RankEvidence:
    source: SourceName
    rank: int
    record_id: str
    raw_score: float
    contribution: float

    def as_dict(self) -> dict[str, str | int | float]:
        return {"source": self.source, "rank": self.rank, "record_id": self.record_id,
                "raw_score": round(self.raw_score, 6),
                "contribution": round(self.contribution, 9)}


@dataclass(frozen=True, slots=True)
class FusedHit:
    item: CatalogItem
    score: float
    evidence: tuple[RankEvidence, ...]

    def as_dict(self) -> dict[str, object]:
        return {"item_id": self.item.item_id, "title": self.item.title,
                "kind": self.item.kind, "score": round(self.score, 9),
                "evidence": [row.as_dict() for row in self.evidence]}


def fuse_rankings(
    catalog: Catalog,
    rankings: dict[SourceName, Sequence[tuple[str, str, float]]],
    *,
    weights: FusionWeights | None = None,
    rrf_k: int = 60,
    limit: int = 5,
    allowed_item_ids: frozenset[str] | None = None,
) -> tuple[FusedHit, ...]:
    """Fuse lists of (item_id, record_id, native_score) in ranked order.

    Inputs must already be correctly ordered. A duplicate item inside any one
    list is rejected instead of silently contributing multiple times.
    ``allowed_item_ids`` provides a second filter boundary for outside callers.
    """
    if type(rrf_k) is not int or not 1 <= rrf_k <= 10_000:
        raise ValueError("rrf_k must be an integer in [1, 10000]")
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer in [1, 1000]")
    chosen_weights = weights or FusionWeights()
    item_map = {item.item_id: item for item in catalog.items}
    if not rankings or set(rankings) - {"bm25", "text", "image"}:
        raise ValueError("rankings must contain known retrieval sources")
    for source, rows in rankings.items():
        if chosen_weights.for_source(source) == 0 and rows:
            raise ValueError(f"nonempty ranking has zero source weight: {source}")
        seen: set[str] = set()
        for item_id, record_id, score in rows:
            if item_id not in item_map or (allowed_item_ids is not None
                                           and item_id not in allowed_item_ids):
                raise ValueError(f"unknown or filtered item in {source}: {item_id}")
            if item_id in seen:
                raise ValueError(f"duplicate item in {source}: {item_id}")
            if not isinstance(record_id, str) or not record_id:
                raise ValueError("source record IDs must be nonempty strings")
            if type(score) not in (int, float) or not math.isfinite(score):
                raise ValueError("native ranking scores must be finite")
            seen.add(item_id)

    active = {source: chosen_weights.for_source(source) for source, rows in rankings.items()
              if rows and chosen_weights.for_source(source) > 0}
    total_weight = sum(active.values())
    if total_weight == 0:
        return ()
    contributions: dict[str, list[RankEvidence]] = {}
    for source in ("bm25", "text", "image"):
        if source not in active:
            continue
        weight = active[source] / total_weight
        for rank, (item_id, record_id, native_score) in enumerate(rankings[source], start=1):
            contribution = weight / (rrf_k + rank)
            contributions.setdefault(item_id, []).append(
                RankEvidence(source, rank, record_id, float(native_score), contribution)
            )
    hits = [FusedHit(item_map[item_id], math.fsum(e.contribution for e in evidence),
                     tuple(evidence)) for item_id, evidence in contributions.items()]
    hits.sort(key=lambda hit: (-hit.score, hit.item.item_id))
    return tuple(hits[:limit])


def search_fused(
    catalog: Catalog,
    query: str,
    *,
    index: VectorIndex | None = None,
    encoder: JointTextImageEmbedder | None = None,
    query_vector: Sequence[float] | None = None,
    catalog_dir: Path | None = None,
    filters: SearchFilters | None = None,
    weights: FusionWeights | None = None,
    rrf_k: int = 60,
    pool_size: int = 50,
    limit: int = 5,
) -> tuple[FusedHit, ...]:
    """Rank filtered catalog items through BM25, text vectors, and image vectors.

    Vector sources require an index and exactly one of an embedding provider or
    a precomputed query vector. A text query is embedded once and reused for
    both vector sources. Index metadata and optionally media bytes are checked.
    """
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    if type(pool_size) is not int or not 1 <= pool_size <= 1000:
        raise ValueError("pool_size must be an integer in [1, 1000]")
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer in [1, 1000]")
    if type(rrf_k) is not int or not 1 <= rrf_k <= 10_000:
        raise ValueError("rrf_k must be an integer in [1, 10000]")
    selected_weights = weights or FusionWeights()
    if index is None and (encoder is not None or query_vector is not None):
        raise ValueError("vector query parameters require an index")
    if index is not None and encoder is not None and query_vector is not None:
        raise ValueError("pass either an encoder or a query_vector, not both")
    if index is not None:
        validate_catalog(index, catalog, catalog_dir=catalog_dir)

    if not query.strip():
        return ()
    allowed = frozenset(item.item_id for item in filter_catalog(catalog.items, filters))
    if not allowed:
        return ()
    rankings: dict[SourceName, list[tuple[str, str, float]]] = {}
    if selected_weights.bm25 > 0:
        lexical = search_catalog(catalog.items, query, filters, method="bm25", limit=pool_size)
        rankings["bm25"] = [(hit.item.item_id, f"text:{hit.item.item_id}", hit.score)
                            for hit in lexical]

    if index is not None:
        available = {row.modality for row in index.records}
        needs_vectors = ((selected_weights.text > 0 and "text" in available)
                         or (selected_weights.image > 0 and "image" in available))
        if needs_vectors:
            if encoder is None and query_vector is None:
                raise ValueError("vector sources require an encoder or query_vector")
            if encoder is not None:
                if (encoder.model_id != index.model_id
                        or encoder.embedding_space_id != index.embedding_space_id):
                    raise VectorIndexError("query encoder does not match the index model identity")
                embedded = encoder.embed_texts([query])
                if len(embedded) != 1:
                    raise VectorIndexError("query encoder returned an unexpected vector count")
                query_vector = embedded[0]
            excluded = frozenset(row.record_id for row in index.records
                                 if row.item_id not in allowed)
            for modality in ("text", "image"):
                if selected_weights.for_source(modality) <= 0 or modality not in available:
                    continue
                hits = search_vectors(index, query_vector, target=modality, k=pool_size,
                                      catalog=catalog, exclude=excluded, unique_items=True)
                rankings[modality] = [(hit.item_id, hit.record_id, hit.score) for hit in hits]

    if not rankings:
        raise ValueError("no enabled retrieval sources are available")
    return fuse_rankings(catalog, rankings, weights=selected_weights, rrf_k=rrf_k,
                         limit=limit, allowed_item_ids=allowed)
