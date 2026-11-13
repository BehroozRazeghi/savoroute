#!/usr/bin/env python3
"""Export the 41 unresolved pilot records for reviewed municipal-boundary checks.

This is a NON-classifying audit. No network access and no city assignment.
Recorded coordinates may represent an OSM node or geometry center rather than entrance.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from savoroute.data.catalog import load_catalog
from savoroute.evidence.review import catalog_digest
from savoroute.services.storage import write_json_file


def unresolved_report(path: str | Path) -> dict:
    catalog = load_catalog(path)
    unresolved = sorted((item for item in catalog.items if item.kind == "restaurant" and item.city is None),
                        key=lambda item: item.item_id)
    rows = [{"item_id": item.item_id, "title": item.title,
             "source_url": item.source_url, "raw_address": item.raw_address,
             "latitude": item.latitude, "longitude": item.longitude,
             "region": item.region, "country": item.country,
             "status": "municipality_unresolved", "assignment": None}
            for item in unresolved]
    return {
        "schema_version": 1, "catalog_digest": catalog_digest(catalog),
        "unresolved_restaurants": len(rows), "records": rows,
        "reference_boundary": "https://gisportal.boston.gov/ArcGIS/rest/services/CityServices/COBBoundary/MapServer/0",
        "limitations": "Unresolved means no evidenced municipality; it does not mean outside Boston. A city label requires a reviewed official polygon or a verified independent source. OSM positions are not guaranteed entrances.",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path,
                        default=Path('data/generated/real-pilot/catalog.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.catalog.resolve() == args.output.resolve():
        parser.error('output must differ from input catalog')
    report = unresolved_report(args.catalog)
    write_json_file(report, args.output)
    print(f"Exported {report['unresolved_restaurants']} unresolved municipalities without assigning cities: {args.output}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
