"""Generate an unlabeled identity-review worksheet from a saved OSM snapshot."""

from __future__ import annotations

from typing import Any

from savoroute.identity.matching import MatchRecord, is_review_candidate
from savoroute.ingestion.osm import parse_osm_candidate, parse_osm_elements
from savoroute.ingestion.sources import IngestionError


def prepare_osm_annotations(payload: Any, *, max_records: int = 80,
                            max_pairs: int = 200) -> dict[str, Any]:
    """Sample candidate and control pairs for manual annotation.

    Deterministic and intentionally stratified: this sample is NOT representative
    of the natural pair prevalence in a full city or source collection.
    """
    if type(max_records) is not int or not 2 <= max_records <= 100:
        raise IngestionError("max_records must be an integer between 2 and 100")
    if type(max_pairs) is not int or not 1 <= max_pairs <= 1000:
        raise IngestionError("max_pairs must be an integer between 1 and 1000")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in parse_osm_elements(payload):
        candidate, ref, _reason = parse_osm_candidate(raw)
        if candidate is None:
            continue
        if ref in seen:
            raise IngestionError(f"duplicate OSM source key: {ref}")
        seen.add(ref)
        item = candidate.item
        rows.append({
            "record_id": ref, "name": item.title, "address": item.location,
            "latitude": candidate.lat, "longitude": candidate.lon,
        })
    if len(rows) < 2:
        raise IngestionError("snapshot contains fewer than two usable restaurant records")
    rows = sorted(rows, key=lambda item: item["record_id"])[:max_records]
    candidate_pairs: list[tuple[str, str]] = []
    control_pairs: list[tuple[str, str]] = []
    for i, left in enumerate(rows):
        a = MatchRecord(left["name"], left["address"], left["latitude"], left["longitude"])
        for right in rows[i + 1:]:
            b = MatchRecord(right["name"], right["address"], right["latitude"], right["longitude"])
            target = candidate_pairs if is_review_candidate(a, b) else control_pairs
            target.append((left["record_id"], right["record_id"]))
    # Include all available candidates first, then controls up to a bounded total.
    selected = (candidate_pairs + control_pairs)[:max_pairs]
    synthetic = payload.get("savoroute_fixture") is True
    provenance = (
        "Unlabeled fictional Overpass-format fixture; independently review each pair"
        if synthetic else
        "Unlabeled OpenStreetMap contributors data (ODbL-1.0); independently review each pair"
    )
    return {
        "schema_version": 1,
        "dataset": {"name": "osm-identity-review", "synthetic": synthetic,
                    "annotation_provenance": provenance},
        "records": rows,
        "pairs": [{"left_id": left, "right_id": right, "same_entity": None}
                  for left, right in selected],
    }
