"""Deterministic catalog audits. Coverage is not evidence of correctness.

No network requests, LLM inference, reverse geocoding, or hidden filling of gaps.
The source-facts sidecar is separate from the canonical retrieval catalog.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from savoroute.domain.models import Catalog, CatalogItem
from savoroute.evidence.review import catalog_digest

_PLACEHOLDER_DESCRIPTIONS = frozenset({
    "restaurant entry from openstreetmap.",
    "restaurant entry from openstreetmap",
})


def informative_description(item: CatalogItem) -> bool:
    return bool(item.description.strip() and item.description.strip().casefold()
                not in _PLACEHOLDER_DESCRIPTIONS)


def _available(item: CatalogItem, field: str, media_ids: set[str]) -> bool:
    if field == "description":
        return informative_description(item)
    if field == "coordinates":
        return item.latitude is not None and item.longitude is not None
    if field == "address":
        # A numeric coordinate or city alone does not count as a street address.
        address = item.raw_address or item.location or ""
        return any(char.isalpha() for char in address) and any(char.isdigit() for char in address)
    if field == "media_refs":
        return item.item_id in media_ids  # merely linked media, NOT verified rights
    if field == "price":
        return item.price_tier is not None
    if field == "source_link":
        return item.source_url is not None
    value = getattr(item, field)
    return bool(value)


_FIELDS = {
    "restaurant": ("city", "coordinates", "address", "cuisines", "description",
                   "dietary_tags", "price", "source_link", "media_refs"),
    "recipe": ("ingredients", "cuisines", "description", "dietary_tags",
               "source_link", "media_refs"),
}
_PRIORITY = {"city": 0, "coordinates": 1, "address": 2, "cuisines": 3,
             "description": 4, "source_link": 5, "ingredients": 6,
             "price": 7, "dietary_tags": 8, "media_refs": 9}


def audit_catalog(catalog: Catalog, *, source_facts: dict[str, Any] | None = None,
                  queue_limit: int = 50) -> dict[str, Any]:
    """Create an exact, digest-bound snapshot of *recorded* field coverage.

    A populated dietary/price/cuisine field is not automatically verified. Source
    observations are a separate category and do not change these coverage counts.
    """
    if not isinstance(queue_limit, int) or isinstance(queue_limit, bool) or not 0 <= queue_limit <= 500:
        raise ValueError("queue_limit must be an integer between 0 and 500")
    if source_facts is not None and source_facts.get("catalog_digest") != catalog_digest(catalog):
        raise ValueError("source facts were derived from a different catalog")
    media_ids = {asset.item_id for asset in catalog.media}
    groups: dict[str, Any] = {}
    queue: list[dict[str, Any]] = []
    for kind, fields in _FIELDS.items():
        records = [item for item in catalog.items if item.kind == kind]
        total = len(records)
        counts = {field: sum(_available(item, field, media_ids) for item in records)
                  for field in fields}
        groups[kind] = {
            "total": total,
            "fields": {field: {"recorded": counts[field], "missing": total - counts[field],
                               "denominator": total,
                               "recorded_pct": round(100 * counts[field] / total, 2) if total else None}
                       for field in fields},
        }
        for item in records:
            missing = [field for field in fields if not _available(item, field, media_ids)]
            if missing:
                missing.sort(key=lambda field: _PRIORITY[field])
                queue.append({"item_id": item.item_id, "kind": kind, "title": item.title,
                              "missing_fields": missing,
                              "priority": _PRIORITY[missing[0]]})
    queue.sort(key=lambda row: (row["priority"], -len(row["missing_fields"]), row["item_id"]))
    result: dict[str, Any] = {
        "schema_version": 1,
        "catalog_digest": catalog_digest(catalog),
        "dataset_name": catalog.dataset_name,
        "synthetic": catalog.synthetic,
        "total_records": len(catalog.items),
        "by_kind": groups,
        "review_queue_total": len(queue),
        "review_queue": queue[:queue_limit],
        "review_queue_limit": queue_limit,
        "interpretation": "Recorded field != independently verified claim. Unknown is not false. "
                          "Dietary/allergen safety, prices, availability and opening times are unverified.",
    }
    if source_facts is not None:
        labels = Counter(fact["field"] for entry in source_facts["records"]
                         for fact in entry["facts"])
        result["source_observations"] = {
            "observed_at": source_facts["observed_at"],
            "osm_snapshot_sha256": source_facts["osm_snapshot_sha256"],
            "records_with_source_observations": sum(bool(row["facts"]) for row in source_facts["records"]),
            "by_field": dict(sorted(labels.items())),
            "verification_status": "unverified_osm_tags",
        }
    return result
