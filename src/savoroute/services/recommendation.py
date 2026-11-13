"""Deterministic recommendations grounded exclusively in catalog records.

No generated venues, menu claims, allergen-safety assertions, or confidence
probabilities. Preference bonuses only rerank already-retrieved candidates.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from savoroute.domain.models import Catalog, CatalogItem
from savoroute.providers.contracts import JointTextImageEmbedder
from savoroute.retrieval.dense import DenseIndex
from savoroute.retrieval.fusion import FusionWeights, RankEvidence, search_fused
from savoroute.retrieval.lexical import SearchFilters, filter_catalog
from savoroute.retrieval.vector import VectorIndex


@dataclass(frozen=True, slots=True)
class RecommendationPreferences:
    cuisines: tuple[str, ...] = ()
    dietary_tags: tuple[str, ...] = ()
    excluded_item_ids: tuple[str, ...] = ()
    preference_strength: float = 0.25

    def __post_init__(self) -> None:
        for name in ("cuisines", "dietary_tags", "excluded_item_ids"):
            rows = getattr(self, name)
            if (not isinstance(rows, tuple) or any(
                not isinstance(value, str) or not value.strip() for value in rows
            ) or len({value.strip().casefold() for value in rows}) != len(rows)):
                raise ValueError(f"{name} must be a tuple of distinct, nonempty strings")
        value = self.preference_strength
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("preference_strength must be a finite number in [0, 1]")


@dataclass(frozen=True, slots=True)
class Recommendation:
    item: CatalogItem
    retrieval_score: float
    score: float
    matched_cuisines: tuple[str, ...]
    matched_dietary_tags: tuple[str, ...]
    evidence: tuple[RankEvidence, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item.item_id, "title": self.item.title,
            "kind": self.item.kind, "description": self.item.description,
            "source": self.item.source, "source_url": self.item.source_url,
            "cuisines": list(self.item.cuisines),
            "dietary_tags": list(self.item.dietary_tags),
            "location": self.item.location, "price_tier": self.item.price_tier,
            "ingredients": list(self.item.ingredients),
            **{field: getattr(self.item, field) for field in (
                "raw_address", "city", "region", "country", "city_id",
                "latitude", "longitude", "city_source",
            )},
            "retrieval_score": round(self.retrieval_score, 9),
            "ranking_score": round(self.score, 9),
            "matched_preferred_cuisines": list(self.matched_cuisines),
            "matched_preferred_dietary_tags": list(self.matched_dietary_tags),
            "retrieval_evidence": [row.as_dict() for row in self.evidence],
            "explanation": self._explain(),
        }

    def _explain(self) -> str:
        """Only refer to recorded provenance and rank positions, never model prose."""
        retrieval = ", ".join(f"{row.source} rank {row.rank}" for row in self.evidence)
        preferences = []
        if self.matched_cuisines:
            preferences.append("catalog cuisine " + ", ".join(self.matched_cuisines))
        if self.matched_dietary_tags:
            preferences.append("catalog dietary tag " + ", ".join(self.matched_dietary_tags))
        clauses = [f"Retrieved through {retrieval}"]
        if preferences:
            clauses.append("Matched preference: " + "; ".join(preferences))
        clauses.append("Catalog source: " + self.item.source)
        return ". ".join(clauses) + "."


@dataclass(frozen=True, slots=True)
class RecommendationResponse:
    query: str
    eligible_items: int
    results: tuple[Recommendation, ...]
    synthetic: bool
    status: str
    filters: SearchFilters

    def as_dict(self) -> dict[str, object]:
        return {
            "query": self.query, "catalog_synthetic": self.synthetic,
            "status": self.status, "eligible_items": self.eligible_items,
            "applied_filters": {
                "kind": self.filters.kind, "cuisine": self.filters.cuisine,
                "location": self.filters.location,
                "city": self.filters.city, "region": self.filters.region,
                "country": self.filters.country,
                "max_price_tier": self.filters.max_price_tier,
                "dietary_tags": list(self.filters.dietary_tags),
            },
            "results": [row.as_dict() for row in self.results],
            "limitations": (
                "Results are based solely on catalog metadata. Opening hours, availability, "
                "ingredient completeness, allergen safety, and current prices are not verified."
            ),
        }


def recommend_items(
    catalog: Catalog, query: str, *,
    filters: SearchFilters | None = None,
    preferences: RecommendationPreferences | None = None,
    index: VectorIndex | DenseIndex | None = None,
    encoder: JointTextImageEmbedder | None = None,
    query_vector: Sequence[float] | None = None,
    catalog_dir: Path | None = None,
    weights: FusionWeights | None = None,
    rrf_k: int = 60,
    pool_size: int = 50,
    limit: int = 5,
) -> RecommendationResponse:
    """Filter, retrieve and softly rerank catalog items; never invent candidates."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer in [1, 1000]")
    prefs = preferences or RecommendationPreferences()
    applied_filters = filters or SearchFilters()
    known = {item.item_id for item in catalog.items}
    unknown = set(prefs.excluded_item_ids) - known
    if unknown:
        raise ValueError(f"excluded_item_ids contain unknown IDs: {sorted(unknown)}")
    excluded = set(prefs.excluded_item_ids)
    eligible = tuple(item for item in filter_catalog(catalog.items, applied_filters)
                     if item.item_id not in excluded)
    if not eligible:
        return RecommendationResponse(query, 0, (), catalog.synthetic, "no_eligible_items",
                                      applied_filters)
    # Retrieve a bounded complete candidate list before user-specific reranking.
    # The fusion service itself limits to 1,000 candidates.
    hits = search_fused(
        catalog, query, index=index, encoder=encoder, query_vector=query_vector,
        catalog_dir=catalog_dir, filters=applied_filters, weights=weights,
        rrf_k=rrf_k, pool_size=pool_size, limit=min(len(catalog.items), 1000),
    )
    preferred_cuisine = {value.strip().casefold() for value in prefs.cuisines}
    preferred_diet = {value.strip().casefold() for value in prefs.dietary_tags}
    denom = len(preferred_cuisine) + len(preferred_diet)
    ranked: list[Recommendation] = []
    for hit in hits:
        if hit.item.item_id in excluded:
            continue
        cuisines = tuple(value for value in hit.item.cuisines
                         if value.casefold() in preferred_cuisine)
        diets = tuple(value for value in hit.item.dietary_tags
                      if value.casefold() in preferred_diet)
        match_ratio = (len(cuisines) + len(diets)) / denom if denom else 0.0
        score = hit.score * (1 + prefs.preference_strength * match_ratio)
        ranked.append(Recommendation(hit.item, hit.score, score, cuisines, diets,
                                     hit.evidence))
    ranked.sort(key=lambda row: (-row.score, -row.retrieval_score, row.item.item_id))
    return RecommendationResponse(query, len(eligible), tuple(ranked[:limit]),
                                  catalog.synthetic,
                                  "ok" if ranked else "no_retrieval_matches",
                                  applied_filters)
