"""Offline metadata-only visit suggestions and explicit confirmation.

No photo files, camera roll, EXIF, HTTP calls, face/food inference, or inferred
visits. Outputs stay on the local filesystem, and only final confirmed history
omits original coordinates and photo IDs. Every suggestion requires review.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from savoroute.domain.models import Catalog
from savoroute.evidence.review import catalog_digest
from savoroute.ingestion.osm import parse_osm_candidate, parse_osm_elements

MAX_PHOTOS = 1_000
MAX_INPUT_BYTES = 512_000
MAX_CLUSTERS = 1_000
EARTH_RADIUS_M = 6_371_008.8
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")


class VisitError(ValueError):
    """Invalid visit metadata, catalog association, or review decision."""


def _expect(value: Any, keys: set[str], context: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise VisitError(f"{context} must contain exactly {', '.join(sorted(keys))}")
    return value


def _digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _bounded_json(path: str | Path) -> Any:
    file = Path(path)
    if not file.is_file() or file.stat().st_size > MAX_INPUT_BYTES:
        raise VisitError("visit input must be an existing JSON file of at most 512 KB")
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise VisitError("visit input must contain UTF-8 JSON") from exc


def _identifier(value: Any, context: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise VisitError(f"{context} must be an opaque ID (1–64 letters, digits, _ or -)")
    return value


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not _TS.fullmatch(value):
        raise VisitError("taken_at requires an ISO-8601 timestamp with explicit timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VisitError("invalid taken_at timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise VisitError("taken_at requires a timezone offset")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _latlon(latitude: Any, longitude: Any, context: str) -> tuple[float, float]:
    if (type(latitude) not in (float, int) or type(longitude) not in (float, int)
            or not math.isfinite(latitude) or not math.isfinite(longitude)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise VisitError(f"{context}: coordinates must be finite and in valid ranges")
    return float(latitude), float(longitude)


def _positive(value: Any, context: str, max_value: int) -> int:
    if type(value) is not int or not 1 <= value <= max_value:
        raise VisitError(f"{context} must be an integer in 1..{max_value}")
    return value


@dataclass(frozen=True, slots=True)
class Photo:
    photo_id: str
    taken_at: datetime
    lat: float
    lon: float


def _photos(payload: Any) -> tuple[Photo, ...]:
    body = _expect(payload, {"schema_version", "user_selected", "photos"}, "photo manifest")
    if type(body["schema_version"]) is not int or body["schema_version"] != 1:
        raise VisitError("unsupported photo manifest schema")
    if body["user_selected"] is not True:
        raise VisitError("photo metadata must be explicitly user-selected")
    rows = body["photos"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_PHOTOS:
        raise VisitError(f"photo manifest requires 1..{MAX_PHOTOS} metadata records")
    photos = []
    seen: set[str] = set()
    for i, raw in enumerate(rows):
        row = _expect(raw, {"photo_id", "taken_at", "latitude", "longitude"}, f"photos[{i}]")
        identifier = _identifier(row["photo_id"], "photo_id")
        if identifier in seen:
            raise VisitError("photo_id must be unique")
        seen.add(identifier)
        lat, lon = _latlon(row["latitude"], row["longitude"], f"photos[{i}]")
        photos.append(Photo(identifier, _timestamp(row["taken_at"]), lat, lon))
    return tuple(sorted(photos, key=lambda p: (p.taken_at, p.photo_id)))


def _distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance; wrapped longitude handles ±180° discontinuity."""
    a, b = math.radians(lat1), math.radians(lat2)
    delta = math.radians((lon2 - lon1 + 180) % 360 - 180)
    h = math.sin((b - a) / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(delta / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(max(h, 0)), math.sqrt(max(1 - h, 0)))


def _center(cluster: list[Photo]) -> tuple[float, float]:
    """Circular longitude centroid; fall back to anchor for degenerate antipodes."""
    lat = sum(photo.lat for photo in cluster) / len(cluster)
    x = sum(math.cos(math.radians(photo.lon)) for photo in cluster)
    y = sum(math.sin(math.radians(photo.lon)) for photo in cluster)
    lon = cluster[0].lon if math.hypot(x, y) < 1e-12 else math.degrees(math.atan2(y, x))
    return lat, lon


def _clusters(
    photos: tuple[Photo, ...], *, gap: int, span: int, radius: int,
) -> list[list[Photo]]:
    """Deterministic contiguous segmentation anchored in time and space.

    A photo must be near the first photo *and* the current centroid, so a chain
    of individually close photographs cannot drift across an entire street.
    """
    groups: list[list[Photo]] = []
    for photo in photos:
        if not groups:
            groups.append([photo])
            continue
        current = groups[-1]
        center_lat, center_lon = _center(current)
        eligible = (
            (photo.taken_at - current[-1].taken_at).total_seconds() <= gap * 60
            and (photo.taken_at - current[0].taken_at).total_seconds() <= span * 60
            and _distance(photo.lat, photo.lon, current[0].lat, current[0].lon) <= radius
            and _distance(photo.lat, photo.lon, center_lat, center_lon) <= radius
        )
        if eligible:
            current.append(photo)
        else:
            groups.append([photo])
    return groups


def _restaurant_positions(catalog: Catalog, osm: Any) -> list[dict[str, Any]]:
    """Use only OSM geometry whose stable source identity exists in this catalog."""
    if not isinstance(osm, dict):
        raise VisitError("OSM input must be an Overpass JSON object")
    rows = parse_osm_elements(osm)
    synthetic = osm.get("savoroute_fixture") is True
    if synthetic != catalog.synthetic:
        raise VisitError("OSM fixture status differs from the catalog")
    locations = []
    seen: set[str] = set()
    for row in rows:
        candidate, ref, _ = parse_osm_candidate(row)
        if candidate is None or candidate.lat is None or candidate.lon is None:
            continue
        item = catalog.get(candidate.item.item_id)
        if item is None:
            continue  # e.g. OSM record held for duplicate review, never admitted
        if item.kind != "restaurant" or item.title != candidate.item.title:
            raise VisitError("OSM source identity does not match the active catalog")
        if not synthetic and item.source_url != f"https://www.openstreetmap.org/{ref}":
            raise VisitError("OSM source URL differs from the active catalog binding")
        if item.item_id in seen:
            raise VisitError("duplicate OSM restaurant identity")
        seen.add(item.item_id)
        locations.append({"item_id": item.item_id, "title": item.title,
                          "source_ref": ref, "latitude": candidate.lat,
                          "longitude": candidate.lon})
    return sorted(locations, key=lambda r: r["item_id"])


def suggest_visits(
    catalog: Catalog,
    osm: Any,
    metadata: Any,
    *,
    gap_minutes: int = 90,
    span_minutes: int = 180,
    cluster_radius_m: int = 200,
    match_radius_m: int = 125,
    max_candidates: int = 5,
) -> dict[str, Any]:
    """Return unconfirmed suggestions; never infer that a restaurant was visited."""
    gap = _positive(gap_minutes, "gap_minutes", 360)
    span = _positive(span_minutes, "span_minutes", 720)
    radius = _positive(cluster_radius_m, "cluster_radius_m", 1_000)
    match = _positive(match_radius_m, "match_radius_m", 1_000)
    maximum = _positive(max_candidates, "max_candidates", 20)
    if gap > span:
        raise VisitError("gap_minutes cannot exceed span_minutes")
    photos = _photos(metadata)
    restaurants = _restaurant_positions(catalog, osm)
    groups = _clusters(photos, gap=gap, span=span, radius=radius)
    if len(groups) > MAX_CLUSTERS:
        raise VisitError("too many visit clusters")
    proposals = []
    for group in groups:
        lat, lon = _center(group)
        candidates = []
        for restaurant in restaurants:
            meters = _distance(lat, lon, restaurant["latitude"], restaurant["longitude"])
            if meters <= match:
                candidates.append({"item_id": restaurant["item_id"],
                                   "title": restaurant["title"],
                                   "source_ref": restaurant["source_ref"],
                                   "distance_m": round(meters, 2)})
        candidates.sort(key=lambda item: (item["distance_m"], item["item_id"]))
        identity = _digest([
            [p.photo_id, _utc_text(p.taken_at), p.lat, p.lon] for p in group
        ])[:20]
        proposals.append({
            "visit_id": f"v_{identity}",
            "photo_ids": [p.photo_id for p in group],
            "photo_count": len(group),
            "started_at": _utc_text(group[0].taken_at),
            "ended_at": _utc_text(group[-1].taken_at),
            "center": {"latitude": round(lat, 7), "longitude": round(lon, 7)},
            "candidates": candidates[:maximum],
        })
    if len({p["visit_id"] for p in proposals}) != len(proposals):
        raise VisitError("visit identity collision")
    return {
        "schema_version": 1,
        "status": "unreviewed",
        "catalog_digest": catalog_digest(catalog),
        "osm_digest": _digest(osm),
        "photo_manifest_digest": _digest(metadata),
        "parameters": {"gap_minutes": gap, "span_minutes": span,
                       "cluster_radius_m": radius, "match_radius_m": match,
                       "max_candidates": maximum},
        "clusters": proposals,
        "limitations": [
            "Clusters indicate proximity in user-provided metadata, not confirmed visits.",
            "Restaurant matches use OSM point/center geometry; positions may be imprecise.",
            "No food recognition, opening-hour, menu, or visit verification is performed.",
        ],
    }


def build_review_template(suggestions: dict[str, Any]) -> dict[str, Any]:
    """Make a private, blank review sheet bound to the exact proposal content."""
    if suggestions.get("schema_version") != 1 or suggestions.get("status") != "unreviewed":
        raise VisitError("unsupported suggestion bundle")
    ids = [row["visit_id"] for row in suggestions["clusters"]]
    if len(ids) != len(set(ids)) or len(ids) > MAX_CLUSTERS:
        raise VisitError("suggestion IDs must be unique and bounded")
    return {"schema_version": 1, "suggestions_digest": _digest(suggestions),
            "decisions": [{"visit_id": identifier, "decision": None, "item_id": None,
                           "reason": None, "reviewed_on": None} for identifier in ids]}


def _review_day(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise VisitError("reviewed_on must be a YYYY-MM-DD date")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError as exc:
        raise VisitError("reviewed_on must be a valid ISO date") from exc
    return value


def finalize_visits(
    catalog: Catalog, suggestions: Any, review: Any,
) -> dict[str, Any]:
    """Export minimally identifying confirmed visits only after complete review."""
    if not isinstance(suggestions, dict) or set(suggestions) != {
        "schema_version", "status", "catalog_digest", "osm_digest",
        "photo_manifest_digest", "parameters", "clusters", "limitations",
    } or suggestions["schema_version"] != 1 or suggestions["status"] != "unreviewed":
        raise VisitError("unsupported suggestion bundle")
    if suggestions["catalog_digest"] != catalog_digest(catalog):
        raise VisitError("suggestions refer to a different catalog version")
    clusters = suggestions["clusters"]
    if not isinstance(clusters, list) or not 1 <= len(clusters) <= MAX_CLUSTERS:
        raise VisitError("suggestions require a bounded cluster list")
    if not isinstance(review, dict):
        raise VisitError("review must be an object")
    _expect(review, {"schema_version", "suggestions_digest", "decisions"}, "review")
    if review["schema_version"] != 1 or review["suggestions_digest"] != _digest(suggestions):
        raise VisitError("review does not match these suggestions")
    decisions = review["decisions"]
    if not isinstance(decisions, list) or len(decisions) != len(clusters):
        raise VisitError("every visit suggestion requires one explicit decision")
    by_id: dict[str, dict[str, Any]] = {}
    for i, decision in enumerate(decisions):
        row = _expect(decision, {"visit_id", "decision", "item_id", "reason", "reviewed_on"},
                      f"decisions[{i}]")
        identifier = _identifier(row["visit_id"], "visit_id")
        if identifier in by_id:
            raise VisitError("duplicate visit decision")
        if row["decision"] not in ("confirm", "reject", "reassign"):
            raise VisitError("each visit must be confirmed, rejected, or reassigned")
        if not isinstance(row["reason"], str) or not 1 <= len(row["reason"].strip()) <= 300:
            raise VisitError("every visit decision requires a concise rationale")
        if any(ord(c) < 32 for c in row["reason"]):
            raise VisitError("visit rationale cannot contain control characters")
        _review_day(row["reviewed_on"])
        by_id[identifier] = row
    if set(by_id) != {group["visit_id"] for group in clusters}:
        raise VisitError("decisions do not cover exactly the proposed visits")
    confirmed = []
    rejects = 0
    for group in clusters:
        choice = by_id[group["visit_id"]]
        if choice["reviewed_on"] < group["started_at"][:10]:
            raise VisitError("review date precedes proposed visit")
        selected_id = choice["item_id"]
        decision = choice["decision"]
        candidate_ids = {row["item_id"] for row in group["candidates"]}
        if decision == "reject":
            if selected_id is not None:
                raise VisitError("rejected visit cannot specify an item")
            rejects += 1
            continue
        if not isinstance(selected_id, str):
            raise VisitError("confirmed or reassigned visit requires an item_id")
        item = catalog.get(selected_id)
        if item is None or item.kind != "restaurant":
            raise VisitError("selected restaurant must exist in the active catalog")
        if decision == "confirm" and selected_id not in candidate_ids:
            raise VisitError("confirm may select only a nearby suggested restaurant")
        if decision == "reassign" and selected_id in candidate_ids:
            raise VisitError("reassign must select a different restaurant, not a candidate")
        confirmed.append({
            "visit_id": group["visit_id"], "item_id": selected_id,
            "decision": decision,
            "started_at": group["started_at"], "ended_at": group["ended_at"],
            "photo_count": group["photo_count"],
            "reviewed_on": choice["reviewed_on"],
        })
    return {
        "schema_version": 1, "catalog_digest": catalog_digest(catalog),
        "suggestions_digest": _digest(suggestions), "review_digest": _digest(review),
        "confirmed_visits": confirmed, "rejected_count": rejects,
        "reviewed_count": len(clusters),
        "limitations": "User-confirmed history; presence and venue identity are user assertions, not independently verified.",
    }


def load_visit_json(path: str | Path) -> Any:
    """Bounded private JSON loader for all local visit files."""
    return _bounded_json(path)
