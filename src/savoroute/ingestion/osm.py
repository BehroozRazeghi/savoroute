"""Bounded OpenStreetMap Overpass snapshots and conservative restaurant admission.

This adapter maps OSM tags directly. It does not use the LLM extraction contract:
OSM tags are structured observations, not quotable prose.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from savoroute.data.catalog import catalog_to_dict, parse_catalog
from savoroute.domain.models import Catalog, CatalogItem
from savoroute.identity.osm_versions import validate_osm_metadata
from savoroute.ingestion.sources import IngestionError
from savoroute.services.storage import json_text, write_json_file, write_json_pair

OSM_LICENSE = "ODbL-1.0"
OSM_ATTRIBUTION = "© OpenStreetMap contributors"
OVERPASS_ENDPOINT = "https://overpass-api.de/api/interpreter"
MAX_RESPONSE_BYTES = 2_000_000
MAX_ELEMENTS = 1000
_ID = re.compile(r"^(node|way|relation)$")


@dataclass(frozen=True, slots=True)
class OsmCandidate:
    item: CatalogItem
    source_ref: str
    location_basis: str
    raw_tags: dict[str, str]
    lat: float | None
    lon: float | None


@dataclass(frozen=True, slots=True)
class OsmDecision:
    source_ref: str
    status: str
    reason: str
    item_id: str | None = None
    candidate_ids: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_ref": self.source_ref, "status": self.status,
            "reason": self.reason, "item_id": self.item_id,
            "candidate_ids": list(self.candidate_ids),
        }


@dataclass(frozen=True, slots=True)
class OsmImportResult:
    catalog: Catalog
    decisions: tuple[OsmDecision, ...]
    canonical_payload_sha256: str
    synthetic_fixture: bool
    admitted_sources: tuple[dict[str, Any], ...]

    def report(self) -> dict[str, Any]:
        return {
            "osm_import_schema_version": 2,
            "catalog_schema_version": self.catalog.schema_version,
            "canonical_payload_sha256": self.canonical_payload_sha256,
            "catalog_sha256": hashlib.sha256(
                json_text(catalog_to_dict(self.catalog)).encode("utf-8")
            ).hexdigest(),
            "synthetic_fixture": self.synthetic_fixture,
            "source": "OpenStreetMap Overpass JSON" if not self.synthetic_fixture else "synthetic Overpass-format fixture",
            "licence": OSM_LICENSE if not self.synthetic_fixture else None,
            "attribution": OSM_ATTRIBUTION if not self.synthetic_fixture else None,
            "decisions": [decision.as_dict() for decision in self.decisions],
            "admitted_sources": list(self.admitted_sources),
        }


def validate_bbox(values: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if len(values) != 4 or not all(math.isfinite(x) for x in values):
        raise IngestionError("bbox requires four finite coordinates")
    south, west, north, east = values
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise IngestionError("bbox order must be south west north east")
    if north - south > 0.05 or east - west > 0.05:
        raise IngestionError("bbox exceeds maximum span of 0.05 degrees per axis")
    return values


def overpass_query(bbox: tuple[float, float, float, float]) -> str:
    south, west, north, east = validate_bbox(bbox)
    coords = ",".join(f"{value:.7f}" for value in (south, west, north, east))
    return f'[out:json][timeout:25];nwr["amenity"="restaurant"]({coords});out center meta;'


def fetch_overpass(bbox: tuple[float, float, float, float], *, contact: str) -> dict[str, Any]:
    """One explicit, bounded request. No retries, parallelism, or background polling."""
    if not isinstance(contact, str) or not 5 <= len(contact) <= 120 or any(
        c in contact for c in "\r\n\t"
    ) or "@" not in contact:
        raise IngestionError("contact must be a valid-looking email address for User-Agent")
    query = overpass_query(bbox)
    data = urlencode({"data": query}).encode("ascii")
    request = Request(
        OVERPASS_ENDPOINT, data=data, method="POST",
        headers={
            "User-Agent": f"Savoroute/0.5.0 (contact: {contact})",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=35) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise IngestionError(f"Overpass request failed: {type(exc).__name__}") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise IngestionError("Overpass response exceeds 2 MB")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestionError("Overpass returned invalid JSON") from exc
    parse_osm_elements(payload)
    return payload


def parse_osm_elements(payload: Any) -> list[Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise IngestionError("Overpass snapshot requires an elements array")
    if len(payload["elements"]) > MAX_ELEMENTS:
        raise IngestionError(f"snapshot exceeds {MAX_ELEMENTS} elements")
    if "remark" in payload:  # often a timeout/error returned as HTTP 200
        raise IngestionError("Overpass snapshot contains a server remark; import aborted")
    return payload["elements"]


def _position(raw: dict[str, Any]) -> tuple[float | None, float | None]:
    obj = raw.get("center") if raw.get("type") != "node" else raw
    if not isinstance(obj, dict):
        return None, None
    lat, lon = obj.get("lat"), obj.get("lon")
    if (type(lat) not in (int, float) or type(lon) not in (int, float)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180):
        return None, None
    return float(lat), float(lon)


def _text(tags: dict[str, str], key: str) -> str:
    value = tags.get(key, "")
    return value.strip() if isinstance(value, str) else ""


def _match_key(text: str) -> str:
    return " ".join(re.findall(r"[\w]+", text.casefold()))


def parse_osm_candidate(raw: Any) -> tuple[OsmCandidate | None, str, str]:
    if not isinstance(raw, dict):
        return None, "unknown", "element is not an object"
    kind, object_id = raw.get("type"), raw.get("id")
    if not isinstance(kind, str) or not _ID.fullmatch(kind) or type(object_id) is not int or object_id <= 0:
        return None, "unknown", "invalid OSM element type or id"
    ref = f"{kind}/{object_id}"
    tags = raw.get("tags")
    if not isinstance(tags, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in tags.items()):
        return None, ref, "missing or invalid tags"
    if tags.get("amenity") != "restaurant":
        return None, ref, "not tagged amenity=restaurant"
    title = _text(tags, "name")
    if not title or len(title) > 180:
        return None, ref, "missing or excessively long name"
    street, number, city = (_text(tags, key) for key in ("addr:street", "addr:housenumber", "addr:city"))
    full_address = _text(tags, "addr:full")
    lat, lon = _position(raw)
    address = ", ".join(part for part in (" ".join(part for part in (number, street) if part), city) if part)
    if full_address:
        location, basis = full_address, "addr:full"
    elif address:
        location, basis = address, "address tags"
    elif lat is not None and lon is not None:
        location, basis = f"{lat:.6f}, {lon:.6f}", "coordinates"
    else:
        return None, ref, "missing address and geometry"
    cuisines = tuple(dict.fromkeys(
        part.strip() for part in _text(tags, "cuisine").split(";") if part.strip()
    ))
    osm_id = f"osm:{ref}"
    item_id = "i_" + hashlib.sha256(osm_id.encode("utf-8")).hexdigest()[:20]
    item = CatalogItem(
        item_id=item_id, kind="restaurant", title=title,
        description="Restaurant entry from OpenStreetMap.",
        cuisines=cuisines, dietary_tags=(), source="OpenStreetMap contributors",
        source_url=None,  # synthetic fixtures must not imply a real OSM listing
        location=location, price_tier=None, ingredients=(),
        raw_address=full_address or address or None,
        city=city or None, region=_text(tags, "addr:state") or None,
        country=_text(tags, "addr:country") or None,
        latitude=lat, longitude=lon,
        city_source="osm:addr:city" if city else None,
    )
    return OsmCandidate(item, ref, basis, tags, lat, lon), ref, ""


def _near(a: OsmCandidate, b: OsmCandidate) -> bool:
    if None in (a.lat, a.lon, b.lat, b.lon):
        return False
    lat1, lon1, lat2, lon2 = a.lat, a.lon, b.lat, b.lon
    # Equirectangular approximation; suitable for a 75 m candidate threshold.
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6_371_000 * math.hypot(x, y) <= 75


def import_osm_snapshot(
    payload: Any, *, base_catalog: Catalog | None = None,
    dataset_name: str = "osm-restaurants", synthetic_fixture: bool = False,
) -> OsmImportResult:
    """Admit unique source IDs; send possible duplicate establishments to review.

    No approximate matches are merged automatically. A source snapshot is not
    interpreted as verified menus, dietary suitability, opening hours, or prices.
    """
    rows = parse_osm_elements(payload)
    fixture_marker = payload.get("savoroute_fixture") is True
    if synthetic_fixture != fixture_marker:
        raise IngestionError(
            "synthetic fixture marker and --synthetic-fixture option must agree"
        )
    if not isinstance(dataset_name, str) or not dataset_name.strip():
        raise IngestionError("dataset name must be nonempty")
    base = base_catalog or Catalog(1, dataset_name, synthetic_fixture, ())
    if base.synthetic != synthetic_fixture:
        raise IngestionError("source dataset synthetic flag differs from catalog")
    items = list(base.items)
    existing_ids = {item.item_id for item in items}
    accepted: list[OsmCandidate] = []
    admitted_sources: list[dict[str, Any]] = []
    decisions: list[OsmDecision] = []
    refs: set[str] = set()
    for raw in rows:
        candidate, ref, reason = parse_osm_candidate(raw)
        if ref != "unknown":
            if ref in refs:
                raise IngestionError(f"duplicate OSM element identity {ref}")
            refs.add(ref)
        if candidate is None:
            decisions.append(OsmDecision(ref, "skipped", reason))
            continue
        version, timestamp = validate_osm_metadata(raw.get("version"), raw.get("timestamp"))
        item = candidate.item
        if item.item_id in existing_ids:
            decisions.append(OsmDecision(ref, "already_imported", "same source identity", item.item_id))
            continue
        name = _match_key(item.title)
        matches = [old.item_id for old in items if _match_key(old.title) == name
                   and _match_key(old.location or "") == _match_key(item.location or "")]
        matches += [old.item.item_id for old in accepted if _match_key(old.item.title) == name
                    and (_match_key(old.item.location or "") == _match_key(item.location or "")
                         or _near(old, candidate))]
        if matches:
            decisions.append(OsmDecision(
                ref, "review", "possible duplicate establishment", item.item_id,
                tuple(dict.fromkeys(matches)),
            ))
            continue
        if not synthetic_fixture:
            item = replace(item, source_url=f"https://www.openstreetmap.org/{ref}")
            candidate = OsmCandidate(item, ref, candidate.location_basis,
                                     candidate.raw_tags, candidate.lat, candidate.lon)
        existing_ids.add(item.item_id)
        accepted.append(candidate)
        admitted_sources.append({
            "source_ref": ref,
            "item_id": item.item_id,
            "location_basis": candidate.location_basis,
            "source_tags": {key: candidate.raw_tags[key] for key in (
                "name", "cuisine", "addr:full", "addr:street", "addr:housenumber", "addr:city",
                "addr:state", "addr:country"
            ) if key in candidate.raw_tags},
            "latitude": candidate.lat, "longitude": candidate.lon,
            "source_version": version, "source_timestamp": timestamp,
            "source_sha256": hashlib.sha256(json.dumps(
                raw, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8")).hexdigest(),
            "description_origin": "adapter-generated identifier of record type",
        })
        items.append(item)
        decisions.append(OsmDecision(ref, "admitted", "source attributes mapped", item.item_id))
    merged_data = catalog_to_dict(base)
    merged_data["items"] = catalog_to_dict(Catalog(1, base.dataset_name, base.synthetic, tuple(items)))["items"]
    merged = parse_catalog(merged_data)
    snapshot_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return OsmImportResult(merged, tuple(decisions), snapshot_hash, synthetic_fixture, tuple(admitted_sources))


def write_osm_import(
    result: OsmImportResult, *, catalog_path: str | Path,
    report_path: str | Path, overwrite: bool = False,
) -> None:
    write_json_pair(
        catalog_to_dict(result.catalog), result.report(), catalog_path=catalog_path,
        report_path=report_path, overwrite=overwrite,
    )


def write_overpass_snapshot(payload: dict[str, Any], path: str | Path, *, overwrite: bool = False) -> None:
    """Persist raw Overpass JSON; never overwrite source snapshots by default."""
    write_json_file(payload, path, overwrite=overwrite)
