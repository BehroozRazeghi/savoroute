"""Single application-service entry point reused by CLI and future adapters."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from savoroute.data.catalog import load_catalog
from savoroute.domain.models import Catalog
from savoroute.providers.contracts import JointTextImageEmbedder
from savoroute.retrieval.dense import DenseIndex
from savoroute.retrieval.fusion import FusedHit, FusionWeights, search_fused
from savoroute.retrieval.lexical import Method, SearchFilters, SearchHit, search_catalog
from savoroute.retrieval.vector import VectorIndex
from savoroute.services.recommendation import (
    RecommendationPreferences,
    RecommendationResponse,
    recommend_items,
)


@dataclass(frozen=True, slots=True)
class DiscoveryService:
    catalog: Catalog

    @classmethod
    def from_path(cls, path: str | None = None) -> DiscoveryService:
        return cls(load_catalog(path))

    def search(
        self,
        query: str,
        *,
        filters: SearchFilters | None = None,
        method: Method = "bm25",
        limit: int = 5,
    ) -> tuple[SearchHit, ...]:
        return search_catalog(self.catalog.items, query, filters, method=method, limit=limit)

    def rank(
        self, query: str, *,
        index: VectorIndex | DenseIndex | None = None,
        encoder: JointTextImageEmbedder | None = None,
        query_vector: Sequence[float] | None = None,
        catalog_dir: Path | None = None,
        filters: SearchFilters | None = None,
        weights: FusionWeights | None = None,
        rrf_k: int = 60,
        pool_size: int = 50,
        limit: int = 5,
    ) -> tuple[FusedHit, ...]:
        """Return catalog-level results from the shared fusion implementation."""
        return search_fused(
            self.catalog, query, index=index, encoder=encoder,
            query_vector=query_vector, catalog_dir=catalog_dir, filters=filters,
            weights=weights, rrf_k=rrf_k, pool_size=pool_size, limit=limit,
        )

    def recommend(
        self, query: str, *, filters: SearchFilters | None = None,
        preferences: RecommendationPreferences | None = None,
        index: VectorIndex | DenseIndex | None = None,
        encoder: JointTextImageEmbedder | None = None,
        query_vector: Sequence[float] | None = None,
        catalog_dir: Path | None = None, weights: FusionWeights | None = None,
        rrf_k: int = 60, pool_size: int = 50, limit: int = 5,
    ) -> RecommendationResponse:
        """Apply metadata constraints and catalog-backed preference reranking."""
        return recommend_items(
            self.catalog, query, filters=filters, preferences=preferences,
            index=index, encoder=encoder, query_vector=query_vector,
            catalog_dir=catalog_dir, weights=weights, rrf_k=rrf_k,
            pool_size=pool_size, limit=limit,
        )
