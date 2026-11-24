"""Deterministic hard constraints, conservative entity links and relevance order.

No model output creates business identity, trusted coordinates or menu evidence.
The query is a SOFT preference; a dish is not an asserted menu offering.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from savoroute.domain.models import CatalogItem
from savoroute.live.contracts import LinkedSource, LiveDiscoveryInput, WebRestaurant
from savoroute.live.validation import _normalize, canonical_cuisine, place_matches

_STOP = frozenset({
    "a", "an", "and", "at", "best", "eat", "find", "food", "for", "in", "me", "near", "or",
    "restaurant", "restaurants", "serving", "the", "to", "traditional", "with",
})


def _terms(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return {term for term in re.findall(r"[^\W_]+", normalized) if len(term) > 2 and term not in _STOP}


def _identity(name: str, city: str, region: str, country: str) -> tuple[str, str, str, str]:
    from savoroute.live.validation import _country_key, _region_key

    # Strip punctuation, but not words or accents; avoid accidental fuzzy merges.
    clean = " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", name).casefold()))
    return clean, _normalize(city), _region_key(region), _country_key(country)


def rank_catalog(items: Iterable[CatalogItem], request: LiveDiscoveryInput) -> list[CatalogItem]:
    """Rank ONLY already-admitted entries; never use ranking to relax hard filters."""
    words = _terms(request.query) - _terms(request.cuisine)

    def key(item: CatalogItem) -> tuple[int, int, str]:
        # Description is source-recorded but does not prove menu availability.
        matches = len(words & _terms(f"{item.title} {item.description}"))
        primary_city = int(_normalize(item.city or "") == _normalize(request.city))
        return -matches, -primary_city, item.item_id

    return sorted(items, key=key)


def rank_web(items: Iterable[WebRestaurant], request: LiveDiscoveryInput) -> list[WebRestaurant]:
    """Use visible source title/name only; no invented ratings or menu evidence."""
    words = _terms(request.query) - _terms(request.cuisine)

    def key(item: WebRestaurant) -> tuple[int, int, str, str]:
        matches = len(words & _terms(f"{item.name} {item.source_title}"))
        primary_city = int(_normalize(item.city) == _normalize(request.city))
        return -matches, -primary_city, _normalize(item.name), item.source_url

    return sorted(items, key=key)


def link_and_dedupe(
    catalog_matches: list[CatalogItem], web_matches: list[WebRestaurant],
) -> tuple[list[WebRestaurant], list[LinkedSource]]:
    """Deduplicate only complete exact identities; retain alternate source URLs."""
    indexed: dict[tuple[str, str, str, str], str] = {}
    for item in catalog_matches:
        if item.city and item.region and item.country:
            indexed[_identity(item.title, item.city, item.region, item.country)] = item.item_id
    kept: list[WebRestaurant] = []
    linked: list[LinkedSource] = []
    for entry in web_matches:
        matched = (indexed.get(_identity(entry.name, entry.city, entry.region, entry.country))
                   if entry.region and entry.country else None)
        if matched is None:
            kept.append(entry)
        else:
            linked.append(LinkedSource(
                catalog_item_id=matched, source_url=entry.source_url,
                source_title=entry.source_title,
            ))
    return kept, linked


def matching_catalog(items: Iterable[CatalogItem], request: LiveDiscoveryInput) -> list[CatalogItem]:
    wanted = canonical_cuisine(request.cuisine)
    matches = [
        item for item in items
        if item.kind == "restaurant" and item.city
        and place_matches(item.city, item.region or "", item.country or "", request)
        and any(canonical_cuisine(c) == wanted for c in item.cuisines)
    ]
    return rank_catalog(matches, request)
