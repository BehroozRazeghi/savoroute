"""Prepare a human review registry from a captured /v1/live/discover response.

No network requests. Generated records are always PENDING, never auto-approved.
Keep review source files private until reviewed and permission-cleared.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from savoroute.live.contracts import WebRestaurant
from savoroute.live.review import LiveReviewRegistry, review_key


def prepare(source: Path, destination: Path) -> int:
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("web_results"), list):
        raise ValueError("Expected a /v1/live/discover JSON response containing web_results")
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()
    for raw in payload["web_results"]:
        item = WebRestaurant.model_validate(raw)
        key = review_key(item)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "name": item.name, "city": item.city, "region": item.region,
            "country": item.country, "cuisine": item.cuisine,
            "source_url": item.source_url, "decision": "pending",
            "reviewer": "", "reviewed_on": "", "evidence_url": "", "evidence_note": "",
        })
    if destination.exists():
        raise FileExistsError("Refusing to overwrite existing human review judgments")
    destination.write_text(
        json.dumps({"schema_version": 1, "records": rows}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    generator = sub.add_parser("prepare")
    generator.add_argument("api_response", type=Path)
    generator.add_argument("--output", type=Path, required=True)
    checker = sub.add_parser("check")
    checker.add_argument("registry", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        count = prepare(args.api_response, args.output)
        print(f"Created {count} PENDING source reviews: {args.output}")
    else:
        registry = LiveReviewRegistry.load(args.registry)
        totals = {state: sum(r.decision == state for r in registry.reviews.values())
                  for state in ("pending", "approved", "rejected")}
        print(json.dumps({"total": len(registry.reviews), **totals}, indent=2))


if __name__ == "__main__":
    main()
