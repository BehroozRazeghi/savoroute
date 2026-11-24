"""Strict opt-in wire contracts; web discoveries are never catalog records."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]


class LiveDiscoveryInput(StrictModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, max_length=180)] = ""
    cuisine: Label
    city: Label
    region: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""
    country: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""
    # "nearby" is an explicitly chosen *set of cities*, NOT a radius or an
    # inferred administrative metro boundary. No geocoding is performed.
    geography_scope: Literal["city", "nearby"] = "city"
    nearby_cities: Annotated[list[Label], Field(max_length=12)] = Field(default_factory=list)
    consent_remote_processing: Literal[True]

    @model_validator(mode="after")
    def validate_geographic_scope(self) -> LiveDiscoveryInput:
        from savoroute.live.validation import _normalize

        chosen = [_normalize(value) for value in self.nearby_cities]
        if len(chosen) != len(set(chosen)) or _normalize(self.city) in chosen:
            raise ValueError("nearby cities must be distinct from each other and the origin")
        if self.geography_scope == "city" and chosen:
            raise ValueError("nearby cities require geography_scope=nearby")
        if self.geography_scope == "nearby" and (
            not chosen or not self.region or not self.country
        ):
            raise ValueError("nearby scope requires nearby cities, region and country")
        return self


class WebRestaurant(StrictModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
    city: Label
    cuisine: Label
    region: str = ""
    country: str = ""
    source_url: Annotated[str, StringConstraints(max_length=2048)]
    source_title: Annotated[str, StringConstraints(max_length=160)]
    source_label: Literal["web_search_source_not_independently_verified"] = (
        "web_search_source_not_independently_verified"
    )


class LinkedSource(StrictModel):
    """Extra web citations for an *exact* catalog identity match, not a merged fact."""

    catalog_item_id: str
    source_url: Annotated[str, StringConstraints(max_length=2048)]
    source_title: str


class LiveDiscoveryOutput(StrictModel):
    api_version: Literal["v1"] = "v1"
    provider: str
    requested_cuisine: str
    requested_city: str
    geography_scope: Literal["city", "nearby"] = "city"
    requested_cities: list[str] = Field(default_factory=list)
    catalog_synthetic: bool = False
    human_review_required: bool = False
    linked_sources: list[LinkedSource] = Field(default_factory=list)
    catalog_results: list[dict[str, object]]
    web_results: list[WebRestaurant]
    limitations: str = (
        "Web discoveries are AI-extracted leads from cited search sources, NOT independent "
        "verification of cuisine, address, operating status, dishes, menus, pricing or safety. "
        "Catalog records remain separate and may be stale. Verify details with the original source."
    )


class LiveStatusOutput(StrictModel):
    human_review_required: bool = False
    api_version: Literal["v1"] = "v1"
    enabled: bool
    consent_required: Literal[True] = True
    limitations: str = "Live web discovery is an opt-in paid external search; disabled by default."


# Strict Responses structured output: all fields required, no additional properties.
LIVE_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["restaurants"],
    "properties": {
        "restaurants": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "city", "region", "country", "cuisines", "source_url"],
                "properties": {
                    "name": {"type": "string"},
                    "city": {"type": "string"},
                    "region": {"type": "string"},
                    "country": {"type": "string"},
                    "cuisines": {"type": "array", "items": {"type": "string"}},
                    "source_url": {"type": "string"},
                },
            },
        },
    },
}


class ProposedRestaurant(StrictModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
    city: Label
    region: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]
    country: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]
    cuisines: Annotated[list[Label], Field(max_length=8)]
    source_url: Annotated[str, StringConstraints(max_length=2048)]


class ProposedResults(StrictModel):
    restaurants: Annotated[list[ProposedRestaurant], Field(max_length=12)]
