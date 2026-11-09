"""Two interpretable, offline retrieval baselines: overlap and BM25.

Filtering is deterministic and is performed before result selection. BM25 uses
full-catalog statistics to avoid changing term weights when metadata filters
change. Neither method computes semantic embeddings or calibrated probabilities.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from savoroute.domain.models import CatalogItem, ItemKind

Method = Literal["bm25", "overlap"]
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> tuple[str, ...]:
    """Intentionally basic English tokenizer. Not a multilingual tokenizer."""
    return tuple(_TOKEN_RE.findall(text.casefold()))


@dataclass(frozen=True, slots=True)
class SearchFilters:
    kind: ItemKind | None = None
    cuisine: str | None = None
    location: str | None = None
    max_price_tier: int | None = None
    dietary_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind is not None and (
            not isinstance(self.kind, str) or self.kind not in {"restaurant", "recipe"}
        ):
            raise ValueError("kind must be 'restaurant', 'recipe', or None")
        if self.max_price_tier is not None and (
            type(self.max_price_tier) is not int or not 1 <= self.max_price_tier <= 4
        ):
            raise ValueError("max_price_tier must be an integer from 1 to 4")
        for field in ("cuisine", "location"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{field} must be a nonempty string or None")
        if not isinstance(self.dietary_tags, tuple) or any(
            not isinstance(tag, str) or not tag.strip() for tag in self.dietary_tags
        ):
            raise ValueError("dietary_tags must contain nonempty strings")


@dataclass(frozen=True, slots=True)
class SearchHit:
    item: CatalogItem
    score: float
    matched_terms: tuple[str, ...]
    method: Method


def filter_catalog(
    items: Iterable[CatalogItem], filters: SearchFilters | None = None
) -> tuple[CatalogItem, ...]:
    """Hard filters; unknown metadata cannot satisfy a requested constraint."""
    f = filters or SearchFilters()
    tags = {tag.strip().casefold() for tag in f.dietary_tags}
    selected: list[CatalogItem] = []
    for item in items:
        if f.kind is not None and item.kind != f.kind:
            continue
        if f.cuisine and f.cuisine.strip().casefold() not in {x.casefold() for x in item.cuisines}:
            continue
        if f.location and (item.location or "").casefold() != f.location.strip().casefold():
            continue
        if f.max_price_tier is not None and (
            item.price_tier is None or item.price_tier > f.max_price_tier
        ):
            continue
        if not tags.issubset({x.casefold() for x in item.dietary_tags}):
            continue
        selected.append(item)
    return tuple(selected)


def _field_tokens(item: CatalogItem) -> tuple[str, ...]:
    parts = [item.title] * 3 + [" ".join(item.cuisines)] * 2
    parts += [item.description, " ".join(item.dietary_tags), " ".join(item.ingredients)]
    if item.location:
        parts.append(item.location)
    return tokenize(" ".join(parts))


def _overlap(item: CatalogItem, query_terms: set[str]) -> float:
    name = set(tokenize(item.title))
    cuisines = set(tokenize(" ".join(item.cuisines)))
    description = set(tokenize(item.description))
    tags = set(tokenize(" ".join(item.dietary_tags)))
    location = set(tokenize(item.location or ""))
    ingredients = set(tokenize(" ".join(item.ingredients)))
    return float(
        5 * len(query_terms & name) + 3 * len(query_terms & cuisines)
        + 2 * len(query_terms & tags) + len(query_terms & description)
        + len(query_terms & location) + len(query_terms & ingredients)
    )


def search_catalog(
    items: Iterable[CatalogItem],
    query: str,
    filters: SearchFilters | None = None,
    *,
    limit: int = 5,
    method: Method = "bm25",
) -> tuple[SearchHit, ...]:
    """Return catalog-backed hits ranked by a transparent lexical baseline.

    Scores are not comparable across different methods, query texts, or datasets.
    Input item IDs must be unique. Empty/whitespace queries return no results.
    """
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive integer")
    if method not in ("bm25", "overlap"):
        raise ValueError("method must be 'bm25' or 'overlap'")
    records = tuple(items)
    if len({item.item_id for item in records}) != len(records):
        raise ValueError("duplicate catalog item_id")
    selected = filter_catalog(records, filters)
    terms = tuple(dict.fromkeys(tokenize(query)))
    if not terms or not selected:
        return ()
    query_set = set(terms)
    scores: dict[str, float] = {}
    if method == "overlap":
        scores = {item.item_id: _overlap(item, query_set) for item in selected}
    else:
        # In a production index, compute these once during indexing and persist them.
        documents = {item.item_id: Counter(_field_tokens(item)) for item in records}
        lengths = {item_id: sum(doc.values()) for item_id, doc in documents.items()}
        avg_length = sum(lengths.values()) / len(lengths)
        df = {term: sum(doc[term] > 0 for doc in documents.values()) for term in terms}
        k1, b = 1.5, 0.75
        for item in selected:
            doc = documents[item.item_id]
            length = lengths[item.item_id]
            score = 0.0
            for term in terms:
                tf = doc[term]
                if tf == 0:
                    continue
                idf = math.log(1 + (len(documents) - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * (tf * (k1 + 1)) / (
                    tf + k1 * (1 - b + b * length / avg_length)
                )
            scores[item.item_id] = score
    hits: list[SearchHit] = []
    for item in selected:
        if scores[item.item_id] <= 0:
            continue
        observed = set(_field_tokens(item))
        hits.append(SearchHit(item, scores[item.item_id],
                              tuple(sorted(query_set & observed)), method))
    hits.sort(key=lambda hit: (-hit.score, hit.item.item_id))
    return tuple(hits[:limit])
