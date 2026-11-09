"""Single application-service entry point reused by CLI and future adapters."""

from __future__ import annotations

from dataclasses import dataclass

from savoroute.data.catalog import load_catalog
from savoroute.domain.models import Catalog
from savoroute.retrieval.lexical import Method, SearchFilters, SearchHit, search_catalog


@dataclass(frozen=True, slots=True)
class DiscoveryService:
    catalog: Catalog

    @classmethod
    def from_path(cls, path: str | None = None) -> DiscoveryService:
        return cls(load_catalog(path))

    def search(
        self,
        query: str,
        *,
        filters: SearchFilters | None = None,
        method: Method = "bm25",
        limit: int = 5,
    ) -> tuple[SearchHit, ...]:
        return search_catalog(self.catalog.items, query, filters, method=method, limit=limit)
