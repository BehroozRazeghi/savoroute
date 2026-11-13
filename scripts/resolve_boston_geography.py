#!/usr/bin/env python3
"""Auditable Boston catalog backfill from the actual City of Boston GIS polygon.

Run in a network-enabled environment, or pass --boundary-file to use a previously
reviewed/downloaded official GeoJSON file. The input catalog is NEVER overwritten.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from savoroute.data.catalog import load_catalog
from savoroute.geography.boston import (
    BOSTON_GIS_LAYER,
    download_official_boston_boundary,
    load_reviewed_boston_boundary,
    validate_boston_geojson,
)
from savoroute.geography.normalization import normalize_osm_catalog, write_normalized_catalog


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path,
                        default=Path("data/generated/real-pilot/catalog.json"))
    parser.add_argument("--osm", type=Path,
                        default=Path("data/generated/real-pilot/frozen/source.json"))
    parser.add_argument("--boundary-file", type=Path,
                        help="Existing City of Boston GeoJSON, previously downloaded from official GIS")
    parser.add_argument("--save-boundary", type=Path,
                        default=Path("data/generated/real-pilot/boston-boundary.geojson"))
    parser.add_argument("--output", type=Path,
                        default=Path("data/generated/real-pilot/catalog-boundary-verified.json"))
    parser.add_argument("--report", type=Path,
                        default=Path("data/generated/real-pilot/geography-boundary-report.json"))
    args = parser.parse_args(argv)
    # Never destroy an existing source, output, boundary, or historic benchmark.
    if args.output.resolve() in (args.catalog.resolve(), args.osm.resolve()):
        parser.error("output must be separate from source files")
    if args.output.resolve() == args.report.resolve():
        parser.error("output and report paths must differ")
    if args.output.exists() or args.report.exists():
        parser.error("output/report already exists; choose fresh paths")
    if args.boundary_file is None:
        if args.save_boundary.exists():
            parser.error("boundary output already exists; use --boundary-file for review")
        if args.save_boundary.resolve() in (args.catalog.resolve(), args.osm.resolve(),
                                             args.output.resolve(), args.report.resolve()):
            parser.error("boundary path must not overwrite any other file")
        print(f"Requesting official City of Boston GeoJSON: {BOSTON_GIS_LAYER}")
        raw = download_official_boston_boundary()
        validate_boston_geojson(raw)
        args.save_boundary.parent.mkdir(parents=True, exist_ok=True)
        # Validate geometry and coordinates before publishing downloaded bytes.
        # Staging avoids leaving a falsely "official" polygon after a failed check.
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=args.save_boundary.parent, prefix=".boston-", suffix=".geojson",
            delete=False,
        ) as temp:
            temp.write(raw)
            staged = Path(temp.name)
        try:
            boundary = load_reviewed_boston_boundary(staged)
            staged.rename(args.save_boundary)
        finally:
            staged.unlink(missing_ok=True)
        boundary_file = args.save_boundary
    else:
        boundary_file = args.boundary_file
        boundary = load_reviewed_boston_boundary(boundary_file)
    catalog = load_catalog(args.catalog)
    if not args.osm.is_file() or args.osm.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("OSM source snapshot must be a local file under 10 MB")
    snapshot = json.loads(args.osm.read_text(encoding="utf-8"))
    result = normalize_osm_catalog(catalog, snapshot, boundary=boundary)
    write_normalized_catalog(result, catalog_path=args.output, report_path=args.report)
    report = result.report
    print(json.dumps({
        "output": str(args.output), "report": str(args.report),
        "official_layer": BOSTON_GIS_LAYER, "boundary_sha256": boundary.sha256,
        "city_from_osm_tag": report["city_from_osm_tag"],
        "city_from_boundary": report["city_from_boundary"],
        "city_unknown": report["city_unknown"],
        "boundary_conflicts": report["boundary_conflicts"],
        "source_tag_outside_boundary": report.get("source_tag_outside_boundary", []),
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as exc:
        print(f"Boston geography was not changed: {exc}", file=sys.stderr)
        sys.exit(1)
