"""Strict catalog validation and bundled demo-data loading (schema v1)."""

from __future__ import annotations

import json
import math
import re
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from savoroute.domain.models import Catalog, CatalogItem, MediaAsset

_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_ITEM_ALLOWED = {
    "item_id", "kind", "title", "description", "cuisines", "dietary_tags",
    "source", "source_url", "location", "price_tier", "ingredients",
    "raw_address", "city", "region", "country", "city_id",
    "latitude", "longitude", "city_source",
}
_MEDIA_ALLOWED = {"media_id", "item_id", "kind", "uri", "source", "caption"}


class CatalogError(ValueError):
    """Invalid catalog schema or violated catalog referential integrity."""


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogError(f"{context} must be an object")
    return value


def _keys(row: dict[str, Any], required: set[str], allowed: set[str], context: str) -> None:
    missing, unexpected = required - row.keys(), row.keys() - allowed
    if missing or unexpected:
        raise CatalogError(
            f"{context}: missing={sorted(missing)}, unknown={sorted(unexpected)}"
        )


def _text(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{context} must be a nonempty string")
    return value.strip()


def _identifier(value: Any, context: str) -> str:
    value = _text(value, context)
    if not _ID.fullmatch(value):
        raise CatalogError(f"{context} must match {_ID.pattern}")
    return value


def _words(value: Any, context: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CatalogError(f"{context} must be an array of nonempty strings")
    result = tuple(_text(item, f"{context}[{index}]") for index, item in enumerate(value))
    if len({item.casefold() for item in result}) != len(result):
        raise CatalogError(f"{context} contains duplicate values")
    return result


def _optional_text(value: Any, context: str) -> str | None:
    return None if value is None else _text(value, context)


def _source_url(value: Any, context: str) -> str | None:
    url = _optional_text(value, context)
    if url is None:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CatalogError(f"{context} must be an http(s) URL")
    return url


def _coordinate(value: Any, context: str, maximum: int) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not -maximum <= value <= maximum:
        raise CatalogError(f"{context} must be a finite coordinate in [-{maximum}, {maximum}]")
    return float(value)


def _geo_fields(row: dict[str, Any], context: str, kind: str) -> dict[str, Any]:
    names = ("raw_address", "city", "region", "country", "city_id", "city_source")
    geo = {name: _optional_text(row.get(name), f"{context}.{name}") for name in names}
    geo["latitude"] = _coordinate(row.get("latitude"), f"{context}.latitude", 90)
    geo["longitude"] = _coordinate(row.get("longitude"), f"{context}.longitude", 180)
    if (geo["latitude"] is None) != (geo["longitude"] is None):
        raise CatalogError(f"{context}: latitude and longitude must both be present or absent")
    if geo["city_id"] is not None and geo["city"] is None:
        raise CatalogError(f"{context}: city_id requires city")
    if geo["city_source"] is not None and geo["city"] is None:
        raise CatalogError(f"{context}: city_source requires city")
    if kind == "recipe" and any(value is not None for value in geo.values()):
        raise CatalogError(f"{context}: recipe must not have geographic fields")
    return geo


def parse_catalog(payload: Any) -> Catalog:
    """Parse versioned JSON; reject misspellings, invalid IDs, and dangling media."""
    data = _object(payload, "catalog")
    _keys(data, {"schema_version", "dataset", "items"},
          {"schema_version", "dataset", "items", "media"}, "catalog")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise CatalogError("catalog.schema_version must equal 1")
    dataset = _object(data["dataset"], "catalog.dataset")
    _keys(dataset, {"name", "synthetic"}, {"name", "synthetic"}, "catalog.dataset")
    name = _text(dataset["name"], "catalog.dataset.name")
    if type(dataset["synthetic"]) is not bool:
        raise CatalogError("catalog.dataset.synthetic must be a boolean")
    if not isinstance(data["items"], list):
        raise CatalogError("catalog.items must be an array")
    items: list[CatalogItem] = []
    ids: set[str] = set()
    for index, value in enumerate(data["items"]):
        context = f"catalog.items[{index}]"
        row = _object(value, context)
        _keys(row, {"item_id", "kind", "title", "description", "cuisines",
                    "dietary_tags", "source"}, _ITEM_ALLOWED, context)
        identifier = _identifier(row["item_id"], f"{context}.item_id")
        if identifier in ids:
            raise CatalogError(f"duplicate item_id: {identifier}")
        ids.add(identifier)
        kind = row["kind"]
        if not isinstance(kind, str) or kind not in {"restaurant", "recipe"}:
            raise CatalogError(f"{context}.kind must be 'restaurant' or 'recipe'")
        location = _optional_text(row.get("location"), f"{context}.location")
        tier = row.get("price_tier")
        if tier is not None and (type(tier) is not int or not 1 <= tier <= 4):
            raise CatalogError(f"{context}.price_tier must be an integer 1..4")
        if kind == "restaurant" and location is None:
            raise CatalogError(f"{context}: restaurant requires a location")
        if kind == "recipe" and (location is not None or tier is not None):
            raise CatalogError(f"{context}: recipe must not have location or price_tier")
        items.append(CatalogItem(
            item_id=identifier,
            kind=kind,
            title=_text(row["title"], f"{context}.title"),
            description=_text(row["description"], f"{context}.description"),
            cuisines=_words(row["cuisines"], f"{context}.cuisines"),
            dietary_tags=_words(row["dietary_tags"], f"{context}.dietary_tags"),
            source=_text(row["source"], f"{context}.source"),
            source_url=_source_url(row.get("source_url"), f"{context}.source_url"),
            location=location,
            price_tier=tier,
            ingredients=_words(row.get("ingredients", []), f"{context}.ingredients"),
            **_geo_fields(row, context, kind),
        ))
    raw_media = data.get("media", [])
    if not isinstance(raw_media, list):
        raise CatalogError("catalog.media must be an array")
    media: list[MediaAsset] = []
    media_ids: set[str] = set()
    for index, value in enumerate(raw_media):
        context = f"catalog.media[{index}]"
        row = _object(value, context)
        _keys(row, {"media_id", "item_id", "kind", "uri", "source"},
              _MEDIA_ALLOWED, context)
        media_id = _identifier(row["media_id"], f"{context}.media_id")
        item_id = _identifier(row["item_id"], f"{context}.item_id")
        if media_id in media_ids:
            raise CatalogError(f"duplicate media_id: {media_id}")
        if item_id not in ids:
            raise CatalogError(f"{context}.item_id references missing item: {item_id}")
        media_ids.add(media_id)
        if row["kind"] != "image":
            raise CatalogError(f"{context}.kind must equal 'image' (schema v1)")
        media.append(MediaAsset(
            media_id=media_id, item_id=item_id, kind="image",
            uri=_text(row["uri"], f"{context}.uri"),
            source=_text(row["source"], f"{context}.source"),
            caption=_optional_text(row.get("caption"), f"{context}.caption"),
        ))
    return Catalog(1, name, dataset["synthetic"], tuple(items), tuple(media))


def load_catalog(path: str | Path | None = None) -> Catalog:
    """Load bundled synthetic data by default, or a user-provided JSON catalog."""
    if path is None:
        text = files("savoroute.resources").joinpath("demo_catalog.json").read_text(
            encoding="utf-8"
        )
    else:
        text = Path(path).read_text(encoding="utf-8")
    return parse_catalog(json.loads(text))


def catalog_to_dict(catalog: Catalog) -> dict[str, Any]:
    """Serialize the canonical catalog using the existing version-1 contract."""
    return {
        "schema_version": catalog.schema_version,
        "dataset": {"name": catalog.dataset_name, "synthetic": catalog.synthetic},
        "items": [
            {
                "item_id": item.item_id, "kind": item.kind, "title": item.title,
                "description": item.description, "cuisines": list(item.cuisines),
                "dietary_tags": list(item.dietary_tags), "source": item.source,
                "source_url": item.source_url, "location": item.location,
                "price_tier": item.price_tier, "ingredients": list(item.ingredients),
                **{field: getattr(item, field) for field in (
                    "raw_address", "city", "region", "country", "city_id",
                    "latitude", "longitude", "city_source",
                ) if getattr(item, field) is not None},
            }
            for item in catalog.items
        ],
        "media": [
            {
                "media_id": asset.media_id, "item_id": asset.item_id, "kind": asset.kind,
                "uri": asset.uri, "source": asset.source, "caption": asset.caption,
            }
            for asset in catalog.media
        ],
    }
