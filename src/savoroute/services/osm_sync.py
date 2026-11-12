"""Idempotent, source-aware OSM catalog updates.

Exact source keys can update OSM-owned records. Suggested entity matches are
review-only; absence from a bounded Overpass snapshot never deletes records.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from savoroute.data.catalog import catalog_to_dict, parse_catalog
from savoroute.domain.models import Catalog, CatalogItem
from savoroute.identity.matching import MatchRecord, is_review_candidate
from savoroute.identity.osm_versions import validate_osm_metadata
from savoroute.identity.registry import EntityRegistry, SourceBinding, item_digest
from savoroute.ingestion.osm import (
    OsmCandidate,
    parse_osm_candidate,
    parse_osm_elements,
)
from savoroute.ingestion.sources import IngestionError
from savoroute.services.storage import json_text, write_json_group


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _review_candidates(item: CatalogItem, candidate: OsmCandidate,
                       catalog: Catalog, registry: EntityRegistry,
                       exclude_id: str | None = None) -> tuple[str, ...]:
    """Conservative blocking; matches are suggestions, never identity decisions."""
    candidates: list[str] = []
    proposed = MatchRecord(item.title, item.location, candidate.lat, candidate.lon)
    for old in catalog.items:
        if old.item_id == exclude_id or old.kind != "restaurant":
            continue
        bindings = registry.bindings_for(old.item_id)
        if not bindings:
            bindings_to_check = (None,)
        else:
            bindings_to_check = bindings
        if any(is_review_candidate(proposed, MatchRecord(
            old.title, old.location,
            binding.latitude if binding else None,
            binding.longitude if binding else None,
        )) for binding in bindings_to_check):
            candidates.append(old.item_id)
    return tuple(sorted(set(candidates)))


def _materialize(candidate: OsmCandidate, synthetic: bool) -> CatalogItem:
    item = candidate.item
    if synthetic:
        return item
    return replace(item, source_url=f"https://www.openstreetmap.org/{candidate.source_ref}")


@dataclass(frozen=True, slots=True)
class SyncDecision:
    source_ref: str
    status: str  # admitted | updated | unchanged | review | skipped
    reason: str
    item_id: str | None = None
    candidates: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"source_ref": self.source_ref, "status": self.status,
                "reason": self.reason, "item_id": self.item_id,
                "candidate_ids": list(self.candidates)}


@dataclass(frozen=True, slots=True)
class OsmSyncResult:
    catalog: Catalog
    registry: EntityRegistry
    decisions: tuple[SyncDecision, ...]
    snapshot_sha256: str

    def report(self) -> dict[str, Any]:
        return {
            "osm_sync_schema_version": 1,
            "snapshot_sha256": self.snapshot_sha256,
            "catalog_sha256": hashlib.sha256(
                json_text(catalog_to_dict(self.catalog)).encode("utf-8")
            ).hexdigest(),
            "synthetic": self.catalog.synthetic,
            "source": "synthetic Overpass-format fixture" if self.catalog.synthetic
                      else "OpenStreetMap Overpass JSON",
            "licence": None if self.catalog.synthetic else "ODbL-1.0",
            "attribution": None if self.catalog.synthetic else "© OpenStreetMap contributors",
            "decisions": [decision.as_dict() for decision in self.decisions],
        }


def sync_osm_snapshot(payload: Any, *, base_catalog: Catalog,
                      registry: EntityRegistry, synthetic_fixture: bool = False) -> OsmSyncResult:
    """Reconcile a bounded OSM snapshot with persistent catalog identities.

    Updates apply only to an existing OSM-owned item with a single OSM source
    binding. Alternate providers may be linked to its identity, but source
    fields are never overwritten by those providers through this workflow.
    """
    rows = parse_osm_elements(payload)
    if (payload.get("savoroute_fixture") is True) != synthetic_fixture:
        raise IngestionError("synthetic fixture marker and --synthetic-fixture must agree")
    if base_catalog.synthetic != synthetic_fixture:
        raise IngestionError("snapshot synthetic flag differs from catalog")
    # Validate all registry references before mutations.
    for binding in registry.bindings:
        if base_catalog.get(binding.item_id) is None:
            raise IngestionError(f"registry references absent item: {binding.item_id}")
    items: dict[str, CatalogItem] = {item.item_id: item for item in base_catalog.items}
    order = [item.item_id for item in base_catalog.items]
    working = registry
    decisions: list[SyncDecision] = []
    seen: set[str] = set()
    for raw in rows:
        candidate, ref, reason = parse_osm_candidate(raw)
        if ref != "unknown":
            if ref in seen:
                raise IngestionError(f"duplicate OSM source key in snapshot: {ref}")
            seen.add(ref)
        prior = working.lookup("osm", ref) if ref != "unknown" else None
        if candidate is None:
            # A previously mapped record with incomplete/changed tags requires review.
            status = "review" if prior is not None else "skipped"
            decisions.append(SyncDecision(ref, status, reason, prior.item_id if prior else None))
            continue
        value = _materialize(candidate, synthetic_fixture)
        try:
            version, timestamp = validate_osm_metadata(raw.get("version"), raw.get("timestamp"))
        except IngestionError as exc:
            decisions.append(SyncDecision(ref, "review", str(exc), prior.item_id if prior else None))
            continue
        sha = _fingerprint(raw)
        # Candidate blocking reads the working catalog, not only the original state.
        current = Catalog(1, base_catalog.dataset_name, base_catalog.synthetic,
                          tuple(items[item_id] for item_id in order), base_catalog.media)
        if prior is None and value.item_id in items:
            decisions.append(SyncDecision(ref, "review", "existing item ID is unbound; bootstrap the registry",
                                          value.item_id))
            continue
        if prior is not None:
            # A known version cannot be overwritten by unversioned or older metadata.
            if prior.source_version is not None:
                if version is None:
                    decisions.append(SyncDecision(ref, "review", "source version missing", prior.item_id))
                    continue
                if version < prior.source_version:
                    decisions.append(SyncDecision(ref, "review", "stale source version", prior.item_id))
                    continue
                if version == prior.source_version and prior.source_sha256 != sha:
                    decisions.append(SyncDecision(ref, "review", "same source version has different content", prior.item_id))
                    continue
                if version > prior.source_version and prior.source_timestamp is not None:
                    if timestamp <= prior.source_timestamp:
                        decisions.append(SyncDecision(ref, "review", "newer version has non-increasing timestamp", prior.item_id))
                        continue
            existing = items[prior.item_id]
            if prior.item_sha256 is None or prior.item_sha256 != item_digest(existing):
                decisions.append(SyncDecision(
                    ref, "review", "catalog item differs from last recorded source state",
                    prior.item_id,
                ))
                continue
            if existing.kind != "restaurant" or existing.source != "OpenStreetMap contributors":
                decisions.append(SyncDecision(ref, "review", "bound item is not OSM-owned",
                                              prior.item_id))
                continue
            osm_bindings = working.bindings_for(prior.item_id, "osm")
            if len(osm_bindings) > 1:
                decisions.append(SyncDecision(ref, "review", "multiple OSM sources bound to item",
                                              prior.item_id))
                continue
            proposed = replace(value, item_id=prior.item_id)
            conflicts = _review_candidates(proposed, candidate, current, working,
                                           exclude_id=prior.item_id)
            if conflicts:
                decisions.append(SyncDecision(ref, "review", "updated attributes overlap another item",
                                              prior.item_id, conflicts))
                continue
            items[prior.item_id] = proposed
            working = working.put(SourceBinding(
                "osm", ref, prior.item_id, sha, item_digest(proposed), candidate.lat, candidate.lon,
                version, timestamp,
            ), current)
            changed = proposed != existing
            decisions.append(SyncDecision(ref, "updated" if changed else "unchanged",
                                          "source fields changed" if changed else "no catalog field changes",
                                          prior.item_id))
            continue
        conflicts = _review_candidates(value, candidate, current, working)
        if conflicts:
            decisions.append(SyncDecision(ref, "review", "possible duplicate establishment",
                                          value.item_id, conflicts))
            continue
        items[value.item_id] = value
        order.append(value.item_id)
        expanded = Catalog(1, base_catalog.dataset_name, base_catalog.synthetic,
                           tuple(items[item_id] for item_id in order), base_catalog.media)
        working = working.put(SourceBinding(
            "osm", ref, value.item_id, sha, item_digest(value), candidate.lat, candidate.lon,
            version, timestamp,
        ), expanded)
        decisions.append(SyncDecision(ref, "admitted", "new source identity", value.item_id))

    merged_payload = catalog_to_dict(base_catalog)
    updated = Catalog(1, base_catalog.dataset_name, base_catalog.synthetic,
                      tuple(items[item_id] for item_id in order), base_catalog.media)
    merged_payload["items"] = catalog_to_dict(updated)["items"]
    checked = parse_catalog(merged_payload)
    return OsmSyncResult(checked, working, tuple(decisions), _fingerprint(payload))


def write_osm_sync(result: OsmSyncResult, *, catalog_path: str | Path,
                   registry_path: str | Path, report_path: str | Path,
                   overwrite: bool = False) -> None:
    """Persist three individually atomic files after preflight checks.

    This is not a database transaction. Keep the source input and report so a
    failed process can be rerun into fresh output paths.
    """
    write_json_group((
        (catalog_path, catalog_to_dict(result.catalog)),
        (registry_path, result.registry.as_dict()),
        (report_path, result.report()),
    ), overwrite=overwrite)
