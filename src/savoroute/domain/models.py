"""Immutable domain entities, independent of storage, models, CLI, and UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ItemKind = Literal["restaurant", "recipe"]
MediaKind = Literal["image"]


@dataclass(frozen=True, slots=True)
class CatalogItem:
    item_id: str
    kind: ItemKind
    title: str
    description: str
    cuisines: tuple[str, ...]
    dietary_tags: tuple[str, ...]
    source: str
    source_url: str | None = None
    location: str | None = None
    price_tier: int | None = None
    ingredients: tuple[str, ...] = ()
    # Additive schema-v1 geography. None means unknown, never a guessed location.
    raw_address: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    city_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    city_source: str | None = None


@dataclass(frozen=True, slots=True)
class MediaAsset:
    """Metadata for an image; `uri` is a reference, never an implicit download."""

    media_id: str
    item_id: str  # explicit foreign key into the catalog
    kind: MediaKind
    uri: str
    source: str
    caption: str | None = None


@dataclass(frozen=True, slots=True)
class Catalog:
    schema_version: int
    dataset_name: str
    synthetic: bool
    items: tuple[CatalogItem, ...]
    media: tuple[MediaAsset, ...] = ()

    def get(self, item_id: str) -> CatalogItem | None:
        return next((item for item in self.items if item.item_id == item_id), None)
