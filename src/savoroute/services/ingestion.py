"""Catalog admission, source lineage, and output persistence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from savoroute.data.catalog import catalog_to_dict, parse_catalog
from savoroute.domain.models import Catalog
from savoroute.ingestion.extraction import ExtractedItem, Extractor
from savoroute.ingestion.sources import IngestionError, SourceBatch
from savoroute.services.storage import json_text, write_json_pair


@dataclass(frozen=True, slots=True)
class IngestionResult:
    catalog: Catalog
    records: tuple[ExtractedItem, ...]
    source_dataset: str
    source_synthetic: bool

    def provenance(self) -> dict[str, Any]:
        return {
            "provenance_schema_version": 1,
            "catalog_schema_version": self.catalog.schema_version,
            "source_dataset": self.source_dataset,
            "source_synthetic": self.source_synthetic,
            "catalog_sha256": hashlib.sha256(
                json_text(catalog_to_dict(self.catalog)).encode("utf-8")
            ).hexdigest(),
            "records": [record.provenance() for record in self.records],
        }


def ingest_sources(
    batch: SourceBatch, extractor: Extractor, *, base_catalog: Catalog
) -> IngestionResult:
    """Complete validation before admitting new items into a canonical catalog."""
    if batch.synthetic != base_catalog.synthetic:
        raise IngestionError("source dataset synthetic flag differs from catalog")
    seen_ids = {item.item_id for item in base_catalog.items}
    records: list[ExtractedItem] = []
    for source in batch.documents:
        record = extractor.extract(source)
        if record.source != source:
            raise IngestionError("extractor returned a record for a different source")
        if record.item.kind != source.kind:
            raise IngestionError("extractor changed the source kind")
        if record.item.item_id in seen_ids:
            raise IngestionError(f"catalog already contains item_id {record.item.item_id}")
        seen_ids.add(record.item.item_id)
        records.append(record)
    payload = catalog_to_dict(base_catalog)
    payload["items"].extend(catalog_to_dict(Catalog(1, "batch", batch.synthetic,
                                                     tuple(rec.item for rec in records)))["items"])
    merged = parse_catalog(payload)
    return IngestionResult(merged, tuple(records), batch.dataset_name, batch.synthetic)


def write_ingestion(
    result: IngestionResult, *, catalog_path: str | Path,
    provenance_path: str | Path, overwrite: bool = False,
) -> None:
    """Persist the catalog and provenance. Files are individually atomic."""
    write_json_pair(
        catalog_to_dict(result.catalog), result.provenance(),
        catalog_path=catalog_path, report_path=provenance_path, overwrite=overwrite,
    )
