"""Deterministic blocking rule for review candidates; never decides entity identity."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MatchRecord:
    name: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None


def normalize(value: str | None) -> str:
    """Casefold, normalize Unicode, and collapse punctuation/whitespace."""
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", value or "").casefold()))


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance; used for conservative candidate generation only."""
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat, dlon = rlat2 - rlat1, math.radians(lon2 - lon1)
    h = (math.sin(dlat / 2) ** 2 +
         math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    return 2 * 6_371_000 * math.asin(min(1.0, math.sqrt(h)))


def is_review_candidate(left: MatchRecord, right: MatchRecord) -> bool:
    """Same normalized name and either same address or within 75 m.

    This is a blocking heuristic, not an entity match. It intentionally misses
    name variants and may suggest distinct branches at the same address.
    """
    name = normalize(left.name)
    if not name or name != normalize(right.name):
        return False
    address = normalize(left.address)
    if address and address == normalize(right.address):
        return True
    if any(value is None for value in (
        left.latitude, left.longitude, right.latitude, right.longitude
    )):
        return False
    return distance_m(
        left.latitude, left.longitude, right.latitude, right.longitude
    ) <= 75
