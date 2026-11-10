"""Input contract for bounded, locally supplied source documents."""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from savoroute.domain.models import ItemKind

MAX_SOURCE_CHARS = 16_000


class IngestionError(ValueError):
    """A source or extraction failed validation."""


def normalize_text(value: str) -> str:
    """Apply NFC and newline normalization without rewriting evidence spans."""
    if not isinstance(value, str):
        raise IngestionError("source text must be a string")
    text = unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip()
    if not text or "\x00" in text or len(text) > MAX_SOURCE_CHARS:
        raise IngestionError(f"source text must contain 1..{MAX_SOURCE_CHARS} characters without NUL")
    return text


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IngestionError(f"{field} must be a nonempty string")
    return value.strip()


def _timestamp(value: Any) -> str:
    text = _nonempty(value, "collected_at")
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IngestionError("collected_at must be ISO 8601 with a timezone") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise IngestionError("collected_at must include a timezone")
    return stamp.isoformat()


def _url(value: Any) -> str | None:
    if value is None:
        return None
    text = _nonempty(value, "source_url")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise IngestionError("source_url must be an HTTP(S) URL without credentials")
    return text


@dataclass(frozen=True, slots=True)
class SourceDocument:
    source_id: str
    kind: ItemKind
    source_name: str
    text: str
    collected_at: str
    source_url: str | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SourceBatch:
    dataset_name: str
    synthetic: bool
    documents: tuple[SourceDocument, ...]


def parse_source_batch(payload: Any) -> SourceBatch:
    """Parse source-batch schema v1. No URL is fetched or source text executed."""
    if not isinstance(payload, dict) or set(payload) != {"source_schema_version", "dataset", "documents"}:
        raise IngestionError("source batch requires source_schema_version, dataset, documents")
    if type(payload["source_schema_version"]) is not int or payload["source_schema_version"] != 1:
        raise IngestionError("source_schema_version must equal 1")
    dataset = payload["dataset"]
    if not isinstance(dataset, dict) or set(dataset) != {"name", "synthetic"}:
        raise IngestionError("dataset must contain name and synthetic")
    name = _nonempty(dataset["name"], "dataset.name")
    if type(dataset["synthetic"]) is not bool:
        raise IngestionError("dataset.synthetic must be a boolean")
    rows = payload["documents"]
    if not isinstance(rows, list) or not rows:
        raise IngestionError("documents must be a nonempty array")
    documents = []
    ids: set[str] = set()
    for index, row in enumerate(rows):
        context = f"documents[{index}]"
        if not isinstance(row, dict) or set(row) - {
            "source_id", "kind", "source_name", "text", "collected_at", "source_url"
        } or {"source_id", "kind", "source_name", "text", "collected_at"} - set(row):
            raise IngestionError(f"{context}: invalid or missing keys")
        source_id = _nonempty(row["source_id"], f"{context}.source_id")
        if len(source_id) > 128:
            raise IngestionError(f"{context}.source_id exceeds 128 characters")
        if source_id in ids:
            raise IngestionError(f"duplicate source_id: {source_id}")
        ids.add(source_id)
        kind = row["kind"]
        if kind not in ("restaurant", "recipe"):
            raise IngestionError(f"{context}.kind must be restaurant or recipe")
        documents.append(SourceDocument(
            source_id=source_id,
            kind=kind,
            source_name=_nonempty(row["source_name"], f"{context}.source_name"),
            text=normalize_text(row["text"]),
            collected_at=_timestamp(row["collected_at"]),
            source_url=_url(row.get("source_url")),
        ))
    return SourceBatch(name, dataset["synthetic"], tuple(documents))
