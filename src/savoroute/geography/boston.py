"""Fetch and validate the Boston municipal polygon from the official GIS service.

This module is intentionally an optional, explicitly invoked ONLINE data-import step.
It does not infer the city's boundary from the pilot collection box, OSM addresses,
or a display-name string. Existing catalog geography remains untouched until
``normalize_osm_catalog`` is invoked with the inspected polygon.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from savoroute.geography.normalization import CityBoundary, load_city_boundary

BOSTON_GIS_LAYER = (
    "https://gisportal.boston.gov/ArcGIS/rest/services/"
    "CityServices/COBBoundary/MapServer/0"
)
BOSTON_CITY_ID = "us-ma-boston"
MAX_BOUNDARY_BYTES = 10 * 1024 * 1024


def official_boundary_url() -> str:
    """Use server-side EPSG:4326 conversion; never export Web Mercator as GeoJSON."""
    params = {
        "where": "1=1",
        "outFields": "CITY",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    return f"{BOSTON_GIS_LAYER}/query?{urlencode(params)}"


def validate_boston_geojson(raw: bytes) -> dict[str, Any]:
    """Fail closed on an ArcGIS error, wrong municipality or unexpected CRS.

    A locally supplied boundary must pass the same review as the downloaded one.
    """
    if not raw or len(raw) > MAX_BOUNDARY_BYTES:
        raise ValueError("Boston boundary response is empty or larger than 10 MB")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Boston GIS response is not UTF-8 GeoJSON") from exc
    if not isinstance(obj, dict) or obj.get("type") != "FeatureCollection":
        raise ValueError("Boston GIS must return a GeoJSON FeatureCollection")
    features = obj.get("features")
    if not isinstance(features, list) or len(features) != 1:
        raise ValueError("Boston GIS must return exactly one city feature")
    feature = features[0]
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise ValueError("Boston boundary does not contain a GeoJSON Feature")
    props = feature.get("properties")
    if not isinstance(props, dict) or str(props.get("CITY", "")).strip().casefold() != "boston":
        raise ValueError("Boston boundary municipality identity could not be verified")
    if obj.get("crs") is not None:
        raise ValueError("Boston boundary must be WGS84 GeoJSON, without a custom CRS")
    if not isinstance(feature.get("geometry"), dict) or feature["geometry"].get("type") not in (
        "Polygon", "MultiPolygon",
    ):
        raise ValueError("Boston boundary geometry is not a polygon")
    return obj


def download_official_boston_boundary(
    *, opener: Callable[..., Any] = urlopen, timeout: int = 30,
) -> bytes:
    """Download only from the pinned official HTTPS GIS query endpoint.

    No generic URL or remote schema is accepted. Callers always validate
    the bytes and record their checksum before any geographic inference.
    """
    request = Request(official_boundary_url(), headers={
        "Accept": "application/geo+json, application/json",
        "User-Agent": "SavoRoute-geo-audit/0.19 (+local operator)",
    })
    with opener(request, timeout=timeout) as response:
        if hasattr(response, "status") and response.status != 200:
            raise ValueError(f"Official boundary returned HTTP {response.status}")
        raw = response.read(MAX_BOUNDARY_BYTES + 1)
    validate_boston_geojson(raw)
    return raw


def load_reviewed_boston_boundary(path: str | Path) -> CityBoundary:
    path = Path(path)
    validate_boston_geojson(path.read_bytes())
    return load_city_boundary(
        path, city="Boston", region="MA", country="US",
        city_id=BOSTON_CITY_ID, source_url=BOSTON_GIS_LAYER,
    )
