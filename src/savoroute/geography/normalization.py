"""Offline, provenance-conscious OSM geography normalization.

No geocoding, collection-bbox inference, network calls, or address substring
classification. Optional, operator-reviewed GeoJSON can resolve missing cities
using a polygon; uncertain records remain unknown.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from savoroute.data.catalog import catalog_to_dict, parse_catalog
from savoroute.domain.models import Catalog, CatalogItem
from savoroute.ingestion.osm import parse_osm_candidate, parse_osm_elements
from savoroute.ingestion.sources import IngestionError
from savoroute.services.storage import json_text, write_json_pair

_MAX_GEOJSON_BYTES = 10_000_000
_MAX_VERTICES = 100_000


@dataclass(frozen=True, slots=True)
class CityBoundary:
    """A reviewed, offline city polygon with an explicit municipality identity."""

    city: str
    region: str
    country: str
    city_id: str
    source_url: str
    sha256: str
    # Geometry is (polygon, ring, (longitude, latitude)) with holes preserved.
    polygons: tuple[tuple[tuple[tuple[float, float], ...], ...], ...]

    def contains(self, latitude: float, longitude: float) -> bool:
        # Boundary points count as inside. Outer ring must contain the point,
        # while all interior rings (holes) must not contain the point.
        return any(
            _in_ring(longitude, latitude, poly[0])
            and not any(_in_ring(longitude, latitude, hole) for hole in poly[1:])
            for poly in self.polygons
        )


def _in_ring(x: float, y: float, ring: tuple[tuple[float, float], ...]) -> bool:
    inside = False
    for i in range(len(ring) - 1):
        x1, y1 = ring[i]
        x2, y2 = ring[i + 1]
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if abs(cross) < 1e-11 and min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2):
            return True
        if (y1 > y) != (y2 > y):
            intersection = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < intersection:
                inside = not inside
    return inside


def load_city_boundary(
    path: str | Path, *, city: str, region: str, country: str,
    city_id: str, source_url: str,
) -> CityBoundary:
    """Load an operator-reviewed GeoJSON polygon, retaining source checksum.

    The geometry must be EPSG:4326 longitude/latitude. Metadata is supplied
    by the operator rather than inferred from inconsistent provider properties.
    """
    labels = (city, region, country, city_id, source_url)
    if any(not isinstance(v, str) or not v.strip() for v in labels):
        raise IngestionError("boundary requires city, region, country, city_id and source_url")
    parsed_url = urlparse(source_url)
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise IngestionError("boundary source_url must be https")
    path = Path(path)
    if path.stat().st_size > _MAX_GEOJSON_BYTES:
        raise IngestionError("boundary GeoJSON exceeds 10 MB")
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise IngestionError("invalid UTF-8 boundary GeoJSON") from exc
    if not isinstance(data, dict):
        raise IngestionError("boundary GeoJSON must be an object")
    if data.get("crs") is not None:  # GeoJSON RFC 7946, WGS84, longitude first
        raise IngestionError("boundary GeoJSON must be WGS84 without a custom CRS")
    if data.get("type") == "FeatureCollection":
        features = data.get("features")
        if not isinstance(features, list) or len(features) != 1:
            raise IngestionError("boundary GeoJSON must contain exactly one city feature")
        geometry = features[0].get("geometry") if isinstance(features[0], dict) else None
    elif data.get("type") == "Feature":
        geometry = data.get("geometry")
    else:
        geometry = data
    if not isinstance(geometry, dict) or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
        raise IngestionError("boundary requires Polygon or MultiPolygon geometry")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list):
        raise IngestionError("boundary coordinates must be arrays")
    raw_polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
    polygons = []
    vertex_count = 0
    for poly in raw_polygons:
        if not isinstance(poly, list) or not poly:
            raise IngestionError("boundary polygon requires a nonempty outer ring")
        rings = []
        for ring in poly:
            if not isinstance(ring, list) or len(ring) < 4:
                raise IngestionError("boundary ring requires >=4 positions")
            positions = []
            for pos in ring:
                if (not isinstance(pos, list) or len(pos) != 2 or any(type(v) not in (float, int) for v in pos)
                        or not all(math.isfinite(v) for v in pos)
                        or not (-180 <= pos[0] <= 180 and -90 <= pos[1] <= 90)):
                    raise IngestionError("invalid boundary longitude/latitude")
                positions.append((float(pos[0]), float(pos[1])))
            if positions[0] != positions[-1]:
                raise IngestionError("boundary ring is not closed")
            vertex_count += len(positions)
            if vertex_count > _MAX_VERTICES:
                raise IngestionError("boundary contains too many vertices")
            rings.append(tuple(positions))
        polygons.append(tuple(rings))
    if not polygons:
        raise IngestionError("boundary has no polygons")
    return CityBoundary(city.strip(), region.strip(), country.strip(), city_id.strip(),
                        source_url.strip(), hashlib.sha256(raw).hexdigest(), tuple(polygons))


@dataclass(frozen=True, slots=True)
class NormalizedCatalog:
    catalog: Catalog
    report: dict[str, Any]


def normalize_osm_catalog(
    catalog: Catalog, snapshot: Any, *, boundary: CityBoundary | None = None,
) -> NormalizedCatalog:
    """Backfill existing OSM-owned items by stable source ID without changing identity.

    If a source city conflicts with a reviewed boundary, retain the source city
    and report the discrepancy instead of hiding it. Entries not in the
    snapshot are left unchanged and never assigned to the snapshot's city.
    """
    rows = parse_osm_elements(snapshot)
    if (snapshot.get("savoroute_fixture") is True) != catalog.synthetic:
        raise IngestionError("source dataset synthetic flag differs from catalog")
    by_id: dict[str, CatalogItem] = {item.item_id: item for item in catalog.items}
    seen_refs = set()
    matched = set()
    conflicts: list[dict[str, str]] = []
    source_tag_outside_boundary: list[str] = []
    for row in rows:
        candidate, ref, _reason = parse_osm_candidate(row)
        if ref != "unknown":
            if ref in seen_refs:
                raise IngestionError(f"duplicate OSM element identity: {ref}")
            seen_refs.add(ref)
        if candidate is None:
            continue
        old = by_id.get(candidate.item.item_id)
        if old is None:
            continue  # snapshot data cannot silently admit new businesses
        if old.kind != "restaurant" or old.source != "OpenStreetMap contributors":
            raise IngestionError(f"item is not OSM-owned: {old.item_id}")
        if old.source_url not in (None, f"https://www.openstreetmap.org/{ref}"):
            raise IngestionError(f"source identity mismatch: {old.item_id}")
        update = candidate.item
        if boundary and update.latitude is not None and update.longitude is not None:
            if boundary.contains(update.latitude, update.longitude):
                if update.city and update.city.casefold() != boundary.city.casefold():
                    conflicts.append({"item_id": old.item_id, "source_city": update.city,
                                      "boundary_city": boundary.city})
                elif update.city is None:
                    update = replace(update, city=boundary.city, region=update.region or boundary.region,
                                     country=update.country or boundary.country, city_id=boundary.city_id,
                                     city_source=f"boundary:{boundary.sha256}")
                else:
                    # Independent source tag and polygon agree. City keeps its tag provenance.
                    update = replace(update, region=update.region or boundary.region,
                                     country=update.country or boundary.country, city_id=boundary.city_id)
            elif update.city and update.city.casefold() == boundary.city.casefold():
                # A tagged Boston record outside the GIS polygon warrants review;
                # do not silently overrule its source metadata (e.g. shoreline).
                source_tag_outside_boundary.append(old.item_id)
        changes = {name: getattr(update, name) for name in (
            "raw_address", "city", "region", "country", "city_id",
            "latitude", "longitude", "city_source",
        ) if getattr(update, name) is not None}
        for name, value in changes.items():
            existing = getattr(old, name)
            if existing is not None and existing != value:
                raise IngestionError(f"geographic field conflict for {old.item_id}.{name}")
        by_id[old.item_id] = replace(old, **changes)
        matched.add(old.item_id)
    updated = parse_catalog(catalog_to_dict(replace(catalog, items=tuple(
        by_id[item.item_id] for item in catalog.items
    ))))
    sha = hashlib.sha256(json_text(catalog_to_dict(updated)).encode()).hexdigest()
    source_sha = hashlib.sha256(json.dumps(
        snapshot, sort_keys=True, ensure_ascii=False,
    ).encode()).hexdigest()
    report: dict[str, Any] = {
        "geography_normalization_schema_version": 1,
        "input_catalog_sha256": hashlib.sha256(
            json_text(catalog_to_dict(catalog)).encode("utf-8")
        ).hexdigest(),
        "catalog_sha256": sha,
        "source_snapshot_sha256": source_sha,
        "boundary": None if boundary is None else {
            "city": boundary.city, "region": boundary.region, "country": boundary.country,
            "city_id": boundary.city_id, "source_url": boundary.source_url,
            "sha256": boundary.sha256,
        },
        "total_items": len(updated.items),
        "matched_osm_items": len(matched),
        "city_from_osm_tag": sum(x.city_source == "osm:addr:city" for x in updated.items),
        "city_from_boundary": sum(bool(x.city_source and x.city_source.startswith("boundary:")) for x in updated.items),
        "city_unknown": sum(x.kind == "restaurant" and x.city is None for x in updated.items),
        "unknown_city_item_ids": [x.item_id for x in updated.items
                                  if x.kind == "restaurant" and x.city is None],
        "coordinates_present": sum(x.latitude is not None for x in updated.items),
        "region_present": sum(x.region is not None for x in updated.items),
        "country_present": sum(x.country is not None for x in updated.items),
        "boundary_conflicts": conflicts,
        "source_tag_outside_boundary": source_tag_outside_boundary,
        "limitations": "Missing cities remain unknown; source tags and reviewed polygons do not establish live business status or address accuracy.",
    }
    return NormalizedCatalog(updated, report)


def write_normalized_catalog(
    result: NormalizedCatalog, *, catalog_path: str | Path, report_path: str | Path,
    overwrite: bool = False,
) -> None:
    write_json_pair(catalog_to_dict(result.catalog), result.report, catalog_path=catalog_path,
                    report_path=report_path, overwrite=overwrite)
