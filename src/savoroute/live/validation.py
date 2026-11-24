"""Fail-closed validation of web leads before showing them in SavoRoute."""

from __future__ import annotations

import ipaddress
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from savoroute.live.contracts import LiveDiscoveryInput, ProposedResults, WebRestaurant

# This small alias table is intentionally conservative, not a cuisine classifier.
# Broader categories such as Middle Eastern cannot satisfy a Persian request.
_CUISINE_EQUIVALENTS = {"persian": "iranian", "iranian": "iranian"}


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def canonical_cuisine(value: str) -> str:
    key = _normalize(value)
    return _CUISINE_EQUIVALENTS.get(key, key)


def _country_key(value: str) -> str:
    key = _normalize(value)
    return "united states" if key in {"us", "usa", "u.s.", "united states of america"} else key


def _region_key(value: str) -> str:
    key = _normalize(value)
    return "ma" if key == "massachusetts" else key


def place_matches(city: str, region: str, country: str, request: LiveDiscoveryInput) -> bool:
    return (
        _normalize(city) == _normalize(request.city)
        and (not request.region or _region_key(region) == _region_key(request.region))
        and (not request.country or _country_key(country) == _country_key(request.country))
    )


def _safe_url(url: str) -> str | None:
    """Validate display-only HTTPS links; never fetch third-party URLs here."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        if (parts.scheme != "https" or not host or parts.username is not None
                or parts.password is not None or parts.port not in (None, 443)):
            return None
        host = host.casefold().rstrip(".")
        if ("." not in host or host in {"localhost", "localhost.localdomain"}
                or host.endswith((".localhost", ".local", ".internal"))):
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            pass
        if any(char in host for char in " \\@#"):
            return None
        return urlunsplit(("https", parts.netloc.lower(), parts.path or "/", parts.query, ""))
    except (ValueError, UnicodeError):
        return None


def _source_key(url: str) -> str | None:
    safe = _safe_url(url)
    if safe is None:
        return None
    parts = urlsplit(safe)
    return urlunsplit(("https", parts.hostname or "", parts.path.rstrip("/"), parts.query, ""))


def filter_source_leads(
    proposed: ProposedResults, request: LiveDiscoveryInput, sources: list[dict[str, str]],
) -> list[WebRestaurant]:
    """Only display city/cuisine matches with exact observed web-tool source URLs.

    The filter verifies a URL was returned by the web tool, not the truth of a webpage.
    All displayed findings retain the explicit unverified-source warning.
    """
    observed: dict[str, tuple[str, str]] = {}
    for source in sources[:60]:
        raw_url = source.get("url", "")
        key = _source_key(raw_url)
        safe_url = _safe_url(raw_url)
        if key and safe_url:
            observed[key] = (safe_url, source.get("title", "")[:160])
    selected: list[WebRestaurant] = []
    seen: set[tuple[str, str]] = set()
    wanted = canonical_cuisine(request.cuisine)
    for restaurant in proposed.restaurants:
        if not place_matches(restaurant.city, restaurant.region, restaurant.country, request):
            continue
        matching = next(
            (label for label in restaurant.cuisines if canonical_cuisine(label) == wanted), None
        )
        if matching is None:
            continue
        source = observed.get(_source_key(restaurant.source_url) or "")
        key = (_normalize(restaurant.name), _normalize(restaurant.city))
        if source is None or key in seen:
            continue
        seen.add(key)
        selected.append(WebRestaurant(
            name=restaurant.name, city=restaurant.city, region=restaurant.region,
            country=restaurant.country, cuisine=matching,
            source_url=source[0], source_title=source[1] or "Web source",
        ))
        if len(selected) == 8:
            break
    return selected



def filter_displayed_leads(
    candidates: list[WebRestaurant], request: LiveDiscoveryInput,
) -> list[WebRestaurant]:
    """A second boundary check for all current and future provider adapters."""
    matching: list[WebRestaurant] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates[:20]:
        if (not place_matches(candidate.city, candidate.region, candidate.country, request)
                or canonical_cuisine(candidate.cuisine) != canonical_cuisine(request.cuisine)
                or _safe_url(candidate.source_url) is None):
            continue
        key = (_normalize(candidate.name), _normalize(candidate.city))
        if key not in seen:
            seen.add(key)
            matching.append(candidate)
        if len(matching) == 8:
            break
    return matching
