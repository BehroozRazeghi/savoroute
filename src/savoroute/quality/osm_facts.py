"""Bounded OSM raw-tag observations with explicit non-verification status.

Uses *only* an already saved source snapshot. Never crawls linked websites,
imports alleged dietary suitability into catalog tags, or checks live hours.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from savoroute.domain.models import Catalog
from savoroute.evidence.review import catalog_digest
from savoroute.ingestion.osm import parse_osm_elements

MAX_SNAPSHOT_BYTES = 10 * 1024 * 1024
MAX_SIDECAR_BYTES = 5 * 1024 * 1024
_TAGS = {
    "website": "website", "contact:website": "website", "website:menu": "menu_url",
    "cuisine": "cuisine_tag", "description": "description_tag", "addr:city": "city_tag",
    "opening_hours": "opening_hours", "outdoor_seating": "outdoor_seating",
    "wheelchair": "wheelchair", "reservation": "reservation",
    "delivery": "delivery", "takeaway": "takeaway",
    "diet:vegan": "diet_vegan", "diet:vegetarian": "diet_vegetarian",
    "diet:gluten_free": "diet_gluten_free",
}
_URL_FIELDS = {"website", "menu_url"}
_ENUMS = {
    "outdoor_seating": {"yes", "no", "limited"},
    "wheelchair": {"yes", "no", "limited", "designated"},
    "reservation": {"yes", "no", "required", "recommended", "only"},
    "delivery": {"yes", "no", "only"},
    "takeaway": {"yes", "no", "only"},
    "diet_vegan": {"yes", "no", "only", "limited"},
    "diet_vegetarian": {"yes", "no", "only", "limited"},
    "diet_gluten_free": {"yes", "no", "only", "limited"},
}
_ID = re.compile(r"^(?:node|way|relation)/[1-9][0-9]*$")
_HASH = re.compile(r"^[a-f0-9]{64}$")


class SourceFactsError(ValueError):
    """Untrusted, malformed or catalog-incompatible source observation data."""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def _safe_text(value: Any, maximum: int = 180) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped or len(stripped) > maximum or any(ord(c) < 32 for c in stripped):
        return None
    return stripped


def _safe_url(value: Any) -> str | None:
    raw = _safe_text(value, 2048)
    if not raw or any(c.isspace() for c in raw):
        return None
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    hostname = parsed.hostname.casefold()
    if hostname in {"localhost"} or hostname.endswith((".local", ".internal", ".localhost")):
        return None
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not ip.is_global:
            return None
    return raw


def _fact(field: str, raw: Any, osm_tag: str) -> dict[str, str] | None:
    value = (_safe_url(raw) if field in _URL_FIELDS else _safe_text(raw))
    if value is None:
        return None
    if field in _ENUMS and value.casefold() not in _ENUMS[field]:
        return None
    return {"field": field, "value": value, "osm_tag": osm_tag}


def _timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) > 40:
        raise SourceFactsError(f"{label} must be an ISO 8601 timestamp with timezone")
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceFactsError(f"{label} is invalid ISO 8601") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise SourceFactsError(f"{label} must have a timezone")
    return value


def _item_id(reference: str) -> str:
    return "i_" + hashlib.sha256(f"osm:{reference}".encode()).hexdigest()[:20]


def osm_snapshot_digest(snapshot: Any) -> str:
    """Canonical JSON digest for cross-checking a sidecar against a loaded snapshot."""
    return _digest(snapshot)


def build_osm_source_facts(catalog: Catalog, snapshot: Any) -> dict[str, Any]:
    """Extract constrained *unverified* source observations for admitted records.

    Source identity is checked against OSM references, not guessed from names.
    Unknown, unsupported and malformed tags are omitted, never inferred.
    """
    if not isinstance(snapshot, dict):
        raise SourceFactsError("snapshot must be an object")
    raw_time = snapshot.get("osm3s", {}).get("timestamp_osm_base") if isinstance(snapshot.get("osm3s"), dict) else None
    observed_at = _timestamp(raw_time, "OSM snapshot timestamp")
    if catalog.synthetic:
        raise SourceFactsError("cannot present synthetic fixture records as public OSM observations")
    admitted = {item.item_id: item for item in catalog.items if item.kind == "restaurant"
                and item.source == "OpenStreetMap contributors"}
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in parse_osm_elements(snapshot):
        if not isinstance(row, dict):
            continue
        kind, numeric_id = row.get("type"), row.get("id")
        if kind not in {"node", "way", "relation"} or type(numeric_id) is not int or numeric_id <= 0:
            continue
        reference = f"{kind}/{numeric_id}"
        item_id = _item_id(reference)
        item = admitted.get(item_id)
        if item is None:
            continue
        if item_id in seen:
            raise SourceFactsError("duplicate OSM item identity in snapshot")
        seen.add(item_id)
        tags = row.get("tags")
        if not isinstance(tags, dict) or tags.get("amenity") != "restaurant":
            raise SourceFactsError(f"invalid OSM restaurant source for {item_id}")
        name = tags.get("name")
        if not isinstance(name, str) or name.strip().casefold() != item.title.casefold():
            raise SourceFactsError(f"OSM source name differs from catalog for {item_id}")
        if item.source_url and item.source_url != f"https://www.openstreetmap.org/{reference}":
            raise SourceFactsError(f"OSM source URL differs from catalog for {item_id}")
        facts: list[dict[str, str]] = []
        keys: set[str] = set()
        for osm_tag, field in _TAGS.items():
            if osm_tag not in tags or field in keys:
                continue
            entry = _fact(field, tags[osm_tag], osm_tag)
            if entry is not None:
                facts.append(entry)
                keys.add(field)
        time = row.get("timestamp")
        if time is not None:
            _timestamp(time, f"timestamp for {reference}")
        matches.append({
            "item_id": item_id, "osm_ref": reference, "osm_element_sha256": _digest(row),
            "source_url": f"https://www.openstreetmap.org/{reference}",
            "source_timestamp": time,
            "facts": sorted(facts, key=lambda entry: entry["field"]),
        })
    # A partially different snapshot is not a valid source for the active catalog.
    if seen != set(admitted):
        raise SourceFactsError(f"source/catalog identity mismatch: {len(set(admitted)-seen)} missing records")
    return {
        "schema_version": 1, "catalog_digest": catalog_digest(catalog),
        "osm_snapshot_sha256": osm_snapshot_digest(snapshot), "observed_at": observed_at,
        "license": "ODbL-1.0", "attribution": "© OpenStreetMap contributors",
        "verification_status": "unverified_osm_tags",
        "records": sorted(matches, key=lambda entry: entry["item_id"]),
    }


def load_source_facts(path: str | Path, catalog: Catalog) -> dict[str, Any]:
    """Fail closed on stale, malformed or fabricated sidecar fields at startup."""
    file = Path(path)
    if not file.is_file() or file.stat().st_size > MAX_SIDECAR_BYTES:
        raise SourceFactsError("source-facts sidecar missing or larger than 5 MB")
    try:
        value = json.loads(file.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise SourceFactsError("invalid source-facts JSON") from exc
    required = {"schema_version", "catalog_digest", "osm_snapshot_sha256", "observed_at",
                "license", "attribution", "verification_status", "records"}
    if not isinstance(value, dict) or set(value) != required or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise SourceFactsError("invalid source-facts top-level schema")
    if (value["catalog_digest"] != catalog_digest(catalog) or
            value["license"] != "ODbL-1.0" or
            value["attribution"] != "© OpenStreetMap contributors" or
            value["verification_status"] != "unverified_osm_tags" or
            not isinstance(value["osm_snapshot_sha256"], str) or
            not _HASH.fullmatch(value["osm_snapshot_sha256"])):
        raise SourceFactsError("source-facts catalog or provenance mismatch")
    _timestamp(value["observed_at"], "source-facts observed_at")
    rows = value["records"]
    if not isinstance(rows, list) or len(rows) > len(catalog.items):
        raise SourceFactsError("invalid source-facts records")
    ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "item_id", "osm_ref", "osm_element_sha256", "source_url", "source_timestamp", "facts",
        }:
            raise SourceFactsError("invalid source-facts record shape")
        item_id, reference = row["item_id"], row["osm_ref"]
        if not isinstance(reference, str) or not _ID.fullmatch(reference) or not isinstance(item_id, str):
            raise SourceFactsError("invalid source-facts source identity")
        item = catalog.get(item_id)
        if (item_id != _item_id(reference) or item_id in ids or item is None
                or item.kind != "restaurant" or item.source != "OpenStreetMap contributors"
                or (item.source_url and item.source_url != row["source_url"])):
            raise SourceFactsError("source-facts record does not match catalog identity")
        ids.add(item_id)
        if (row["source_url"] != f"https://www.openstreetmap.org/{reference}"
                or not isinstance(row["osm_element_sha256"], str)
                or not _HASH.fullmatch(row["osm_element_sha256"])):
            raise SourceFactsError("invalid source identity/provenance hash")
        if row["source_timestamp"] is not None:
            _timestamp(row["source_timestamp"], "source timestamp")
        facts = row["facts"]
        if not isinstance(facts, list) or len(facts) > len(set(_TAGS.values())):
            raise SourceFactsError("invalid source fact list")
        names: set[str] = set()
        for fact in facts:
            if not isinstance(fact, dict) or set(fact) != {"field", "value", "osm_tag"}:
                raise SourceFactsError("invalid source fact shape")
            field, tag = fact["field"], fact["osm_tag"]
            if not isinstance(tag, str) or _TAGS.get(tag) != field or field in names:
                raise SourceFactsError("unsupported or duplicate source fact")
            if _fact(field, fact["value"], tag) != fact:
                raise SourceFactsError("invalid source fact value")
            names.add(field)
    return value


def read_osm_snapshot(path: str | Path) -> Any:
    p = Path(path)
    if not p.is_file() or p.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise SourceFactsError("OSM snapshot must be a local file under 10 MB")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise SourceFactsError("invalid OSM snapshot JSON") from exc
