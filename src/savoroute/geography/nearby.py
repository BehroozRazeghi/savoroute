"""Deterministic spatial discovery from an explicitly supplied OSM snapshot.

OSM centroids are *reference geometry*, not building entrances or verified
business locations. No geocoding, external requests, or inferred coordinates.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from savoroute.domain.models import Catalog
from savoroute.ingestion.osm import parse_osm_candidate, parse_osm_elements

EARTH_RADIUS_M = 6_371_008.8


class GeographyError(ValueError):
    """Source identity, coordinates, or spatial query is invalid."""


def validated_coordinates(lat: Any, lon: Any) -> tuple[float, float]:
    if (type(lat) not in (int, float) or type(lon) not in (int, float)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180):
        raise GeographyError("latitude/longitude must be finite and within coordinate bounds")
    return float(lat), float(lon)


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine great-circle distance with wrapped longitude, also at the dateline."""
    a, b = math.radians(lat1), math.radians(lat2)
    delta = math.radians((lon2 - lon1 + 180) % 360 - 180)
    h = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(delta / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(max(h, 0)), math.sqrt(max(1 - h, 0)))


def restaurant_positions(catalog: Catalog, osm: Any) -> list[dict[str, Any]]:
    """Bind only admitted OSM geometry to current canonical catalog entities.

    The stable source ID and name must match; unadmitted duplicate-review
    candidates never become searchable. A changed OSM snapshot remains a new
    source observation and is identified by its digest, not a silent catalog edit.
    """
    if not isinstance(osm, dict):
        raise GeographyError("OSM input must be a saved Overpass JSON object")
    rows = parse_osm_elements(osm)
    synthetic = osm.get("savoroute_fixture") is True
    if synthetic != catalog.synthetic:
        raise GeographyError("OSM fixture status differs from the catalog")
    locations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        candidate, ref, _ = parse_osm_candidate(row)
        if candidate is None or candidate.lat is None or candidate.lon is None:
            continue
        item = catalog.get(candidate.item.item_id)
        if item is None:
            continue
        if item.kind != "restaurant" or item.title != candidate.item.title:
            raise GeographyError("OSM source identity does not match active catalog")
        if not synthetic and item.source_url != f"https://www.openstreetmap.org/{ref}":
            raise GeographyError("OSM source URL differs from active catalog binding")
        if item.item_id in seen:
            raise GeographyError("duplicate admitted OSM restaurant identity")
        seen.add(item.item_id)
        locations.append({
            "item_id": item.item_id, "title": item.title, "source_ref": ref,
            "latitude": candidate.lat, "longitude": candidate.lon,
            "geometry_basis": "node" if row["type"] == "node" else "bbox_center",
        })
    return sorted(locations, key=lambda row: row["item_id"])


@dataclass(frozen=True, slots=True)
class NearbyIndex:
    catalog: Catalog
    positions: tuple[dict[str, Any], ...]
    source_sha256: str

    @classmethod
    def from_snapshot(cls, catalog: Catalog, osm: Any) -> NearbyIndex:
        positions = tuple(restaurant_positions(catalog, osm))
        if not positions:
            raise GeographyError("OSM snapshot contains no admitted restaurant geometry")
        canonical = json.dumps(osm, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return cls(catalog, positions, hashlib.sha256(canonical.encode()).hexdigest())

    def search(self, latitude: float, longitude: float, *, radius_m: int = 2000,
               limit: int = 20, cuisine: str | None = None) -> list[dict[str, Any]]:
        lat, lon = validated_coordinates(latitude, longitude)
        if type(radius_m) is not int or not 25 <= radius_m <= 20_000:
            raise GeographyError("radius_m must be an integer between 25 and 20000")
        if type(limit) is not int or not 1 <= limit <= 50:
            raise GeographyError("limit must be an integer between 1 and 50")
        if cuisine is not None and (not isinstance(cuisine, str) or not 1 <= len(cuisine) <= 120):
            raise GeographyError("cuisine must be 1..120 characters")
        found = []
        for entry in self.positions:
            item = self.catalog.get(entry["item_id"])
            if item is None:
                continue
            if cuisine is not None and cuisine.casefold() not in [x.casefold() for x in item.cuisines]:
                continue
            meters = distance_m(lat, lon, entry["latitude"], entry["longitude"])
            if meters <= radius_m:
                found.append({
                    "item": item, "distance_m": meters,
                    "geometry_basis": entry["geometry_basis"],
                    "source_ref": entry["source_ref"],
                })
        found.sort(key=lambda row: (row["distance_m"], row["item"].item_id))
        results = found[:limit]
        for row in results:
            row["distance_m"] = round(row["distance_m"], 1)
        return results
