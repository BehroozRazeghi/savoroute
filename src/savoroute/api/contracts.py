"""Version-1 HTTP wire contracts, separate from immutable domain dataclasses."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StringConstraints,
    field_validator,
    model_validator,
)

from savoroute.retrieval.fusion import FusionWeights
from savoroute.retrieval.lexical import SearchFilters
from savoroute.services.recommendation import RecommendationPreferences

Nonempty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
QueryText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FilterInput(WireModel):
    kind: Literal["restaurant", "recipe"] | None = None
    cuisine: Nonempty | None = None
    location: Nonempty | None = None
    max_price_tier: Annotated[int, Field(strict=True, ge=1, le=4)] | None = None
    dietary_tags: Annotated[tuple[Nonempty, ...], Field(max_length=20)] = ()
    city: Nonempty | None = None
    region: Nonempty | None = None
    country: Nonempty | None = None

    def as_domain(self) -> SearchFilters:
        return SearchFilters(
            kind=self.kind,
            cuisine=self.cuisine,
            location=self.location, city=self.city, region=self.region, country=self.country,
            max_price_tier=self.max_price_tier,
            dietary_tags=self.dietary_tags,
        )


class SearchInput(WireModel):
    query: QueryText
    filters: FilterInput = Field(default_factory=FilterInput)
    method: Literal["bm25", "overlap"] = "bm25"
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 5


class FusionWeightsInput(WireModel):
    bm25: Annotated[FiniteFloat, Field(ge=0)] = 1.0
    text: Annotated[FiniteFloat, Field(ge=0)] = 1.0
    image: Annotated[FiniteFloat, Field(ge=0)] = 1.0

    @model_validator(mode="after")
    def require_active_source(self) -> FusionWeightsInput:
        if self.bm25 + self.text + self.image <= 0:
            raise ValueError("at least one fusion weight must be positive")
        return self

    def as_domain(self) -> FusionWeights:
        return FusionWeights(self.bm25, self.text, self.image)


class RankInput(WireModel):
    query: QueryText
    filters: FilterInput = Field(default_factory=FilterInput)
    weights: FusionWeightsInput | None = None
    query_vector: Annotated[tuple[FiniteFloat, ...], Field(min_length=1, max_length=4096)] | None = None
    rrf_k: Annotated[int, Field(strict=True, ge=1, le=10_000)] = 60
    pool_size: Annotated[int, Field(strict=True, ge=1, le=1000)] = 50
    limit: Annotated[int, Field(strict=True, ge=1, le=100)] = 5

    @field_validator("query_vector", mode="before")
    @classmethod
    def reject_boolean_coordinates(cls, values: object) -> object:
        if isinstance(values, (list, tuple)) and any(type(x) is bool for x in values):
            raise ValueError("query_vector must contain numeric coordinates, not booleans")
        return values


class PreferencesInput(WireModel):
    cuisines: Annotated[tuple[Nonempty, ...], Field(max_length=20)] = ()
    dietary_tags: Annotated[tuple[Nonempty, ...], Field(max_length=20)] = ()
    excluded_item_ids: Annotated[tuple[Identifier, ...], Field(max_length=1000)] = ()
    preference_strength: Annotated[FiniteFloat, Field(ge=0, le=1)] = 0.25

    @model_validator(mode="after")
    def no_duplicates(self) -> PreferencesInput:
        for field in ("cuisines", "dietary_tags", "excluded_item_ids"):
            values = getattr(self, field)
            if len({x.casefold() for x in values}) != len(values):
                raise ValueError(f"{field} contains duplicate values")
        return self

    def as_domain(self) -> RecommendationPreferences:
        return RecommendationPreferences(
            cuisines=self.cuisines,
            dietary_tags=self.dietary_tags,
            excluded_item_ids=self.excluded_item_ids,
            preference_strength=self.preference_strength,
        )


class RecommendInput(RankInput):
    preferences: PreferencesInput = Field(default_factory=PreferencesInput)


class ItemOutput(WireModel):
    item_id: str
    kind: Literal["restaurant", "recipe"]
    title: str
    description: str
    cuisines: list[str]
    dietary_tags: list[str]
    ingredients: list[str]
    source: str
    source_url: str | None
    location: str | None
    price_tier: int | None
    raw_address: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    city_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    city_source: str | None = None


class ItemListOutput(WireModel):
    api_version: Literal["v1"] = "v1"
    total: int
    offset: int
    limit: int
    items: list[ItemOutput]


class SearchHitOutput(WireModel):
    item: ItemOutput
    score: float
    matched_terms: list[str]
    method: Literal["bm25", "overlap"]


class SearchOutput(WireModel):
    api_version: Literal["v1"] = "v1"
    query: str
    catalog_synthetic: bool
    results: list[SearchHitOutput]
    limitations: str


class RankEvidenceOutput(WireModel):
    source: Literal["bm25", "text", "image"]
    rank: int
    record_id: str
    raw_score: float
    contribution: float


class RankHitOutput(WireModel):
    item: ItemOutput
    score: float
    evidence: list[RankEvidenceOutput]


class RankOutput(WireModel):
    api_version: Literal["v1"] = "v1"
    query: str
    catalog_synthetic: bool
    mode: Literal["bm25_only", "hybrid"]
    results: list[RankHitOutput]
    limitations: str


class RecommendationItemOutput(WireModel):
    item_id: str
    title: str
    kind: Literal["restaurant", "recipe"]
    description: str
    source: str
    source_url: str | None
    cuisines: list[str]
    dietary_tags: list[str]
    location: str | None
    price_tier: int | None
    ingredients: list[str]
    raw_address: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    city_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    city_source: str | None = None
    retrieval_score: float
    ranking_score: float
    matched_preferred_cuisines: list[str]
    matched_preferred_dietary_tags: list[str]
    retrieval_evidence: list[RankEvidenceOutput]
    explanation: str


class AppliedFiltersOutput(WireModel):
    kind: Literal["restaurant", "recipe"] | None
    cuisine: str | None
    location: str | None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    max_price_tier: int | None
    dietary_tags: list[str]


class RecommendationOutput(WireModel):
    api_version: Literal["v1"] = "v1"
    query: str
    catalog_synthetic: bool
    status: Literal["ok", "no_eligible_items", "no_retrieval_matches"]
    eligible_items: int
    applied_filters: AppliedFiltersOutput
    results: list[RecommendationItemOutput]
    limitations: str


class MetaOutput(WireModel):
    api_version: Literal["v1"] = "v1"
    package_version: str
    dataset_name: str
    catalog_synthetic: bool
    catalog_items: int
    catalog_media: int
    index_backend: Literal["none", "json", "sqlite", "faiss-hnsw"]
    server_encoder_enabled: bool
    geography_enabled: bool
    geography_restaurants: int
    reviewed_media_enabled: bool
    source_facts_enabled: bool = False
    source_facts_records: int = 0
    recipe_notes_enabled: bool = False
    recipe_notes_records: int = 0



class RecipeNotesItemOutput(WireModel):
    api_version: Literal["v1"] = "v1"
    item_id: str
    review_status: Literal["source_transcribed_unverified", "not_configured", "no_record"]
    source_url: str | None
    source_revision_url: str | None
    source_checked_on: str | None
    source_attribution: str | None
    source_license: str | None
    source_license_url: str | None
    adaptation_notice: str | None
    ingredients: list[str]
    steps: list[str]
    limitations: str


class SourceFactOutput(WireModel):
    field: Literal["website", "menu_url", "cuisine_tag", "description_tag", "city_tag",
                   "opening_hours", "outdoor_seating", "wheelchair",
                   "reservation", "delivery", "takeaway", "diet_vegan", "diet_vegetarian",
                   "diet_gluten_free"]
    value: str
    osm_tag: str


class SourceFactsItemOutput(WireModel):
    api_version: Literal["v1"] = "v1"
    item_id: str
    observed_at: str | None
    source_url: str | None
    source_timestamp: str | None
    attribution: str | None
    license: str | None
    verification_status: Literal["unverified_osm_tags", "not_configured", "no_record"]
    facts: list[SourceFactOutput]
    limitations: str


class ReviewedClaimOutput(WireModel):
    claim_id: str
    item_id: str
    kind: Literal["cuisine", "menu_url", "image_url", "descriptive_note"]
    value: str
    source_url: str
    observed_on: str
    license: str | None
    attribution: str | None
    reviewed_on: str


class EvidenceItemOutput(WireModel):
    item_id: str
    catalog_synthetic: bool
    reviewed_claims: list[ReviewedClaimOutput]
    menu_status: Literal["reviewed_reference", "not_recorded"]
    limitations: str


class NearbyItemOutput(WireModel):
    item: ItemOutput
    distance_m: float
    geometry_basis: Literal["node", "bbox_center"]
    source_ref: str


class NearbyOutput(WireModel):
    api_version: Literal["v1"] = "v1"
    catalog_synthetic: bool
    source_sha256: str
    geometry_restaurants: int
    radius_m: int
    results: list[NearbyItemOutput]
    limitations: str


class ReviewedImageOutput(WireModel):
    asset_id: str
    input_sha256: str
    modifications: str
    claim_id: str
    item_id: str
    sha256: str
    width: int
    height: int
    license: str
    attribution: str
    source_url: str
    image_reference_url: str
    observed_on: str
    reviewed_on: str


class ReviewedMediaListOutput(WireModel):
    api_version: Literal["v1"] = "v1"
    item_id: str
    images: list[ReviewedImageOutput]
    limitations: str
