"""Strict opt-in wire contracts; web discoveries are never catalog records."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=80)]


class LiveDiscoveryInput(StrictModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, max_length=180)] = ""
    cuisine: Label
    city: Label
    region: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""
    country: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = ""
    consent_remote_processing: Literal[True]


class WebRestaurant(StrictModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
    city: Label
    cuisine: Label
    region: str = ""
    country: str = ""
    source_url: str
    source_title: Annotated[str, StringConstraints(max_length=160)]
    source_label: Literal["web_search_source_not_independently_verified"] = (
        "web_search_source_not_independently_verified"
    )


class LiveDiscoveryOutput(StrictModel):
    api_version: Literal["v1"] = "v1"
    provider: str
    requested_cuisine: str
    requested_city: str
    catalog_results: list[dict[str, object]]
    web_results: list[WebRestaurant]
    limitations: str = (
        "Web discoveries are AI-extracted leads from cited search sources, NOT independent "
        "verification of cuisine, address, operating status, dishes, menus, pricing or safety. "
        "Catalog records remain separate and may be stale. Verify details with the original source."
    )


class LiveStatusOutput(StrictModel):
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
