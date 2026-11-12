"""Validation of OpenStreetMap object version and UTC edit timestamp metadata."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from savoroute.ingestion.sources import IngestionError


def validate_osm_metadata(version: Any, timestamp: Any) -> tuple[int | None, str | None]:
    """Validate an OSM element's version and UTC edit timestamp as a pair."""
    if version is None and timestamp is None:
        return None, None  # older, metadata-free local snapshots
    if type(version) is not int or version < 1 or not isinstance(timestamp, str):
        raise IngestionError("OSM version and timestamp must be present together")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", timestamp):
        raise IngestionError("OSM timestamp must use YYYY-MM-DDTHH:MM:SSZ")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IngestionError("OSM timestamp is not a valid UTC datetime") from exc
    if parsed.tzinfo != UTC:
        raise IngestionError("OSM timestamp must be UTC")
    return version, timestamp
