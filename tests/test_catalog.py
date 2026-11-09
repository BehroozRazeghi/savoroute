"""Schema and referential integrity tests."""

import copy
import json
from importlib.resources import files

import pytest

from savoroute.data.catalog import CatalogError, load_catalog, parse_catalog


def payload():
    return json.loads(files("savoroute.resources").joinpath("demo_catalog.json").read_text())


def test_bundled_catalog_loads():
    catalog = load_catalog()
    assert catalog.schema_version == 1
    assert catalog.synthetic
    assert len(catalog.items) == 12
    assert len(catalog.media) == 0
    assert catalog.get("p001").kind == "recipe"
    assert catalog.get("missing") is None


def test_repo_sample_matches_bundled():
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    assert load_catalog(repo / "data/sample/catalog.json") == load_catalog()


@pytest.mark.parametrize("change", [
    lambda p: p.update(schema_version=True),
    lambda p: p.update(other="unrecognized"),
    lambda p: p["dataset"].update(synthetic="yes"),
    lambda p: p["items"].append(copy.deepcopy(p["items"][0])),
    lambda p: p["items"][0].update(title=""),
    lambda p: p["items"][0].update(kind="hotel"),
    lambda p: p["items"][0].update(price_tier=True),
    lambda p: p["items"][0].update(cuisines="Italian"),
    lambda p: p["items"][0].update(dietary_tags=["vegan", "VEGAN"]),
    lambda p: p["items"][0].update(item_id="Bad ID"),
    lambda p: p["items"][0].update(location=None),
    lambda p: p["items"][0].update(source_url="ftp://example.org/a"),
    lambda p: p["items"][6].update(price_tier=2),
])
def test_invalid_catalog_rejected(change):
    p = payload()
    change(p)
    with pytest.raises(CatalogError):
        parse_catalog(p)


def test_explicit_image_join():
    p = payload()
    p["media"] = [{"media_id": "img001", "item_id": "p001", "kind": "image",
                   "uri": "images/illustration.png", "source": "synthetic_demo"}]
    catalog = parse_catalog(p)
    assert catalog.media[0].item_id == "p001"
    assert catalog.media[0].kind == "image"


@pytest.mark.parametrize("field,value", [
    ("item_id", "unknown"),
    ("media_id", "INVALID ID"),
    ("kind", "audio"),
    ("uri", ""),
])
def test_invalid_media_rejected(field, value):
    p = payload()
    row = {"media_id": "img001", "item_id": "p001", "kind": "image",
           "uri": "images/illustration.png", "source": "synthetic_demo"}
    row[field] = value
    p["media"] = [row]
    with pytest.raises(CatalogError):
        parse_catalog(p)


def test_duplicate_media_id_rejected():
    p = payload()
    row = {"media_id": "img001", "item_id": "p001", "kind": "image",
           "uri": "images/illustration.png", "source": "synthetic_demo"}
    p["media"] = [row, row.copy()]
    with pytest.raises(CatalogError, match="duplicate media_id"):
        parse_catalog(p)
