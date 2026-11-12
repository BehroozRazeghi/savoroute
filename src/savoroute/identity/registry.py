"""Source-to-catalog bindings, independent of the catalog-v1 JSON schema.

An item ID identifies a Savoroute entity. A source key identifies a provider
record, not necessarily a distinct real-world business. Linking two source
keys to one item is an explicit operator decision; name similarity alone never
creates an identity link.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from savoroute.data.catalog import catalog_to_dict
from savoroute.domain.models import Catalog, CatalogItem
from savoroute.identity.osm_versions import validate_osm_metadata
from savoroute.ingestion.sources import IngestionError
from savoroute.services.storage import json_text, write_json_file

_PROVIDER = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_OSM_REF = re.compile(r"^(node|way|relation)/[1-9][0-9]*$")


def _source_key(provider: str, source_ref: str) -> tuple[str, str]:
    if not isinstance(provider, str) or not _PROVIDER.fullmatch(provider):
        raise IngestionError("provider must be a lowercase identifier (1–32 characters)")
    if (not isinstance(source_ref, str) or not 1 <= len(source_ref) <= 256
            or source_ref != source_ref.strip()
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in source_ref)):
        raise IngestionError("source_ref must be a nonempty, single-line identifier")
    if provider == "osm" and not _OSM_REF.fullmatch(source_ref):
        raise IngestionError("OSM source_ref must look like node/123, way/123 or relation/123")
    return provider, source_ref


def _coordinates(lat: Any, lon: Any) -> tuple[float | None, float | None]:
    if lat is None and lon is None:
        return None, None
    if (type(lat) not in (int, float) or type(lon) not in (int, float)
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180):
        raise IngestionError("latitude and longitude must both be valid finite coordinates")
    return float(lat), float(lon)


def item_digest(item: CatalogItem) -> str:
    """Fingerprint fields managed in the canonical catalog, excluding media."""
    return hashlib.sha256(json.dumps(
        asdict(item), sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceBinding:
    provider: str
    source_ref: str
    item_id: str
    source_sha256: str | None = None
    item_sha256: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    source_version: int | None = None
    source_timestamp: str | None = None

    def __post_init__(self) -> None:
        _source_key(self.provider, self.source_ref)
        if not isinstance(self.item_id, str) or not self.item_id:
            raise IngestionError("binding.item_id must be nonempty")
        if self.source_sha256 is not None and (
            not isinstance(self.source_sha256, str)
            or not _SHA256.fullmatch(self.source_sha256)
        ):
            raise IngestionError("binding.source_sha256 must be a lowercase SHA-256 digest")
        if self.item_sha256 is not None and (
            not isinstance(self.item_sha256, str) or not _SHA256.fullmatch(self.item_sha256)
        ):
            raise IngestionError("binding.item_sha256 must be a lowercase SHA-256 digest")
        _coordinates(self.latitude, self.longitude)
        if self.provider == "osm":
            validate_osm_metadata(self.source_version, self.source_timestamp)
        elif self.source_version is not None or self.source_timestamp is not None:
            raise IngestionError("source version metadata is supported only for OSM bindings")

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "source_ref": self.source_ref,
            "item_id": self.item_id,
            "source_sha256": self.source_sha256,
            "item_sha256": self.item_sha256,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "source_version": self.source_version,
            "source_timestamp": self.source_timestamp,
        }


@dataclass(frozen=True, slots=True)
class EntityRegistry:
    bindings: tuple[SourceBinding, ...] = ()

    def lookup(self, provider: str, source_ref: str) -> SourceBinding | None:
        return next((b for b in self.bindings
                     if (b.provider, b.source_ref) == (provider, source_ref)), None)

    def bindings_for(self, item_id: str, provider: str | None = None) -> tuple[SourceBinding, ...]:
        return tuple(b for b in self.bindings if b.item_id == item_id
                     and (provider is None or b.provider == provider))

    def put(self, binding: SourceBinding, catalog: Catalog) -> EntityRegistry:
        if catalog.get(binding.item_id) is None:
            raise IngestionError(f"binding references missing item: {binding.item_id}")
        previous = self.lookup(binding.provider, binding.source_ref)
        if previous is not None and previous.item_id != binding.item_id:
            raise IngestionError("source key already bound to a different item; no implicit relink")
        remaining = tuple(
            b for b in self.bindings
            if (b.provider, b.source_ref) != (binding.provider, binding.source_ref)
        )
        return EntityRegistry(tuple(sorted(
            (*remaining, binding), key=lambda b: (b.provider, b.source_ref)
        )))

    def as_dict(self) -> dict[str, Any]:
        return {"registry_schema_version": 2,
                "bindings": [binding.as_dict() for binding in self.bindings]}


def parse_registry(payload: Any, catalog: Catalog) -> EntityRegistry:
    if not isinstance(payload, dict) or set(payload) != {"registry_schema_version", "bindings"}:
        raise IngestionError("registry must contain only registry_schema_version and bindings")
    version = payload["registry_schema_version"]
    if type(version) is not int or version not in (1, 2):
        raise IngestionError("registry_schema_version must be 1 or 2")
    if not isinstance(payload["bindings"], list):
        raise IngestionError("registry.bindings must be an array")
    registry = EntityRegistry()
    fields = {"provider", "source_ref", "item_id", "source_sha256",
              "item_sha256", "latitude", "longitude"}
    if version == 2:
        fields |= {"source_version", "source_timestamp"}
    for i, row in enumerate(payload["bindings"]):
        if not isinstance(row, dict) or set(row) != fields:
            raise IngestionError(f"invalid binding fields at index {i}")
        binding = SourceBinding(**row)
        if registry.lookup(binding.provider, binding.source_ref) is not None:
            raise IngestionError("duplicate source key in registry")
        registry = registry.put(binding, catalog)
    return registry


def load_registry(path: str | Path, catalog: Catalog) -> EntityRegistry:
    try:
        return parse_registry(json.loads(Path(path).read_text(encoding="utf-8")), catalog)
    except json.JSONDecodeError as exc:
        raise IngestionError("registry is not valid JSON") from exc


def bootstrap_osm_registry(catalog: Catalog, report: Any) -> EntityRegistry:
    """Seed bindings from an unmodified v0.3.0 OSM import report.

    The report digest must match the supplied catalog, preventing a stale
    provenance report from silently binding source IDs to the wrong catalog.
    """
    if not isinstance(report, dict) or report.get("osm_import_schema_version") not in (1, 2):
        raise IngestionError("bootstrap requires an OSM import report (schema v1 or v2)")
    digest = hashlib.sha256(json_text(catalog_to_dict(catalog)).encode("utf-8")).hexdigest()
    if report.get("catalog_sha256") != digest:
        raise IngestionError("OSM report catalog digest does not match input catalog")
    if report.get("synthetic_fixture") is not catalog.synthetic:
        raise IngestionError("OSM report synthetic flag differs from catalog")
    sources = report.get("admitted_sources")
    if not isinstance(sources, list):
        raise IngestionError("OSM report missing admitted_sources")
    registry = EntityRegistry()
    for source in sources:
        if not isinstance(source, dict):
            raise IngestionError("OSM report admitted_sources must contain objects")
        try:
            source_ref, item_id = source["source_ref"], source["item_id"]
        except KeyError as exc:
            raise IngestionError("OSM report missing source identity") from exc
        _source_key("osm", source_ref)
        if not isinstance(item_id, str):
            raise IngestionError("OSM report item ID must be a string")
        expected_id = "i_" + hashlib.sha256(
            f"osm:{source_ref}".encode()
        ).hexdigest()[:20]
        if item_id != expected_id:
            raise IngestionError("OSM report source key and item ID disagree")
        item = catalog.get(item_id)
        if item is None:
            raise IngestionError(f"OSM report references missing item: {item_id}")
        if item.kind != "restaurant" or item.source != "OpenStreetMap contributors":
            raise IngestionError("OSM report references a record without OSM provenance")
        expected_url = f"https://www.openstreetmap.org/{source_ref}"
        if catalog.synthetic and item.source_url is not None:
            raise IngestionError("synthetic OSM catalog cannot contain real OSM source URLs")
        if not catalog.synthetic and item.source_url != expected_url:
            raise IngestionError("OSM report source URL disagrees with catalog provenance")
        binding = SourceBinding(
            provider="osm", source_ref=source_ref, item_id=item_id,
            item_sha256=item_digest(item),
            latitude=source.get("latitude"), longitude=source.get("longitude"),
            source_sha256=source.get("source_sha256") if report["osm_import_schema_version"] == 2 else None,
            source_version=source.get("source_version") if report["osm_import_schema_version"] == 2 else None,
            source_timestamp=source.get("source_timestamp") if report["osm_import_schema_version"] == 2 else None,
        )
        if registry.lookup(binding.provider, binding.source_ref) is not None:
            raise IngestionError("duplicate OSM source identity in report")
        registry = registry.put(binding, catalog)
    return registry


def link_source(registry: EntityRegistry, catalog: Catalog, *, provider: str,
                source_ref: str, item_id: str) -> EntityRegistry:
    """Record a manually reviewed identity association; do not merge fields."""
    key = _source_key(provider, source_ref)
    if registry.lookup(*key) is not None:
        raise IngestionError("source key already exists; manual relinking is not supported")
    if provider == "osm" and catalog.get(item_id) is not None and catalog.get(item_id).kind != "restaurant":
        raise IngestionError("OSM source keys can only bind restaurant items")
    return registry.put(SourceBinding(provider, source_ref, item_id), catalog)


def write_registry(registry: EntityRegistry, path: str | Path) -> None:
    write_json_file(registry.as_dict(), path)
