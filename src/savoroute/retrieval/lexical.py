"""Deterministic lexical baselines with reusable, catalog-bound index statistics.

Filtering precedes result selection. BM25 document frequency and average length
are computed over the *whole* catalog, even when a query has hard filters.
Scores are retrieval scores, not calibrated probabilities.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from savoroute.domain.models import CatalogItem, ItemKind

Method = Literal["bm25", "overlap"]
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> tuple[str, ...]:
    """Intentionally basic English tokenizer; not a multilingual tokenizer."""
    return tuple(_TOKEN_RE.findall(text.casefold()))


@dataclass(frozen=True, slots=True)
class SearchFilters:
    kind: ItemKind | None = None
    cuisine: str | None = None
    location: str | None = None
    max_price_tier: int | None = None
    dietary_tags: tuple[str, ...] = ()
    city: str | None = None
    region: str | None = None
    country: str | None = None

    def __post_init__(self) -> None:
        if self.kind is not None and (
            not isinstance(self.kind, str) or self.kind not in {"restaurant", "recipe"}
        ):
            raise ValueError("kind must be 'restaurant', 'recipe', or None")
        if self.max_price_tier is not None and (
            type(self.max_price_tier) is not int or not 1 <= self.max_price_tier <= 4
        ):
            raise ValueError("max_price_tier must be an integer from 1 to 4")
        for name in ("cuisine", "location", "city", "region", "country"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a nonempty string or None")
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


def _place_key(value: str | None) -> str:
    """Normalize Unicode and spacing for equality, not substring geocoding."""
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def filter_catalog(
    items: Iterable[CatalogItem], filters: SearchFilters | None = None
) -> tuple[CatalogItem, ...]:
    """Hard filters: missing metadata cannot satisfy an explicit constraint."""
    f = filters or SearchFilters()
    tags = {tag.strip().casefold() for tag in f.dietary_tags}
    selected: list[CatalogItem] = []
    for item in items:
        if f.kind is not None and item.kind != f.kind:
            continue
        if f.cuisine and f.cuisine.strip().casefold() not in {x.casefold() for x in item.cuisines}:
            continue
        # Legacy location accepts exact address or source-recorded city only.
        # A street containing "Boston" is not evidence of Boston city identity.
        if f.location and _place_key(f.location) not in {
            _place_key(item.location), _place_key(item.city),
        }:
            continue
        if f.city and _place_key(f.city) != _place_key(item.city):
            continue
        if f.region and _place_key(f.region) != _place_key(item.region):
            continue
        if f.country and _place_key(f.country) != _place_key(item.country):
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


def _overlap_fields(item: CatalogItem) -> tuple[frozenset[str], ...]:
    """Field-specific tokens and weights match the original overlap baseline."""
    return (
        frozenset(tokenize(item.title)),
        frozenset(tokenize(" ".join(item.cuisines))),
        frozenset(tokenize(" ".join(item.dietary_tags))),
        frozenset(tokenize(item.description)),
        frozenset(tokenize(item.location or "")),
        frozenset(tokenize(" ".join(item.ingredients))),
    )


_OVERLAP_WEIGHTS = (5, 3, 2, 1, 1, 1)


@dataclass(frozen=True, slots=True)
class LexicalIndex:
    """In-memory index built once from a fixed tuple of immutable catalog items.

    Index contents cannot be mutated through public attributes. A new catalog
    revision requires a new index; there is no implicit cross-catalog cache.
    """

    items: tuple[CatalogItem, ...]
    _documents: tuple[Mapping[str, int], ...] = field(repr=False)
    _lengths: tuple[int, ...] = field(repr=False)
    _average_length: float = field(repr=False)
    _document_frequency: Mapping[str, int] = field(repr=False)
    _postings: Mapping[str, tuple[int, ...]] = field(repr=False)
    _overlap_tokens: tuple[tuple[frozenset[str], ...], ...] = field(repr=False)
    _positions: Mapping[str, int] = field(repr=False)

    @classmethod
    def build(cls, items: Iterable[CatalogItem]) -> LexicalIndex:
        records = tuple(items)
        positions = {item.item_id: pos for pos, item in enumerate(records)}
        if len(positions) != len(records):
            raise ValueError("duplicate catalog item_id")
        if not records:
            return cls(records, (), (), 0.0, MappingProxyType({}),
                       MappingProxyType({}), (), MappingProxyType({}))

        documents: list[Mapping[str, int]] = []
        lengths: list[int] = []
        frequencies: Counter[str] = Counter()
        postings: dict[str, list[int]] = defaultdict(list)
        for position, item in enumerate(records):
            counts = Counter(_field_tokens(item))
            documents.append(MappingProxyType(dict(counts)))
            lengths.append(sum(counts.values()))
            for term in counts:
                frequencies[term] += 1
                postings[term].append(position)
        return cls(
            records, tuple(documents), tuple(lengths), sum(lengths) / len(records),
            MappingProxyType(dict(frequencies)),
            MappingProxyType({term: tuple(indices) for term, indices in postings.items()}),
            tuple(_overlap_fields(item) for item in records),
            MappingProxyType(positions),
        )

    def search(
        self, query: str, filters: SearchFilters | None = None, *,
        limit: int = 5, method: Method = "bm25",
    ) -> tuple[SearchHit, ...]:
        """Search fixed catalog with stable BM25/overlap scores and ID tie-breaks."""
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        if method not in ("bm25", "overlap"):
            raise ValueError("method must be 'bm25' or 'overlap'")
        terms = tuple(dict.fromkeys(tokenize(query)))
        if not terms or not self.items:
            return ()
        query_set = set(terms)
        candidate_positions = {
            pos for term in terms for pos in self._postings.get(term, ())
        }
        if not candidate_positions:
            return ()

        # Keep the same full-catalog IDF with and without metadata constraints.
        selected = filter_catalog(self.items, filters)
        hits: list[SearchHit] = []
        k1, b = 1.5, 0.75
        for item in selected:
            position = self._positions[item.item_id]
            if position not in candidate_positions:
                continue
            if method == "overlap":
                overlap = self._overlap_tokens[position]
                score = float(sum(weight * len(query_set & values)
                                  for weight, values in zip(_OVERLAP_WEIGHTS, overlap, strict=True)))
            else:
                document = self._documents[position]
                length = self._lengths[position]
                score = 0.0
                for term in terms:
                    tf = document.get(term, 0)
                    if tf == 0:
                        continue
                    df = self._document_frequency[term]
                    idf = math.log(1 + (len(self.items) - df + 0.5) / (df + 0.5))
                    score += idf * (tf * (k1 + 1)) / (
                        tf + k1 * (1 - b + b * length / self._average_length)
                    )
            if score > 0:
                hits.append(SearchHit(item, score, tuple(sorted(query_set.intersection(
                    self._documents[position]
                ))), method))
        hits.sort(key=lambda hit: (-hit.score, hit.item.item_id))
        return tuple(hits[:limit])


def search_catalog(
    items: Iterable[CatalogItem],
    query: str,
    filters: SearchFilters | None = None,
    *,
    limit: int = 5,
    method: Method = "bm25",
    lexical_index: LexicalIndex | None = None,
) -> tuple[SearchHit, ...]:
    """Existing stateless API; optionally reuse an index bound to this exact tuple.

    Caller-owned iterables use a one-off index. The shared DiscoveryService
    creates its index once; the vector/fusion layers can reuse it by injection.
    """
    if lexical_index is None:
        lexical_index = LexicalIndex.build(items)
    elif not isinstance(items, tuple) or items is not lexical_index.items:
        raise ValueError("lexical index belongs to a different catalog tuple")
    return lexical_index.search(query, filters, limit=limit, method=method)
