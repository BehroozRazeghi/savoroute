"""Convert a captured real discovery API response into an UNREVIEWED evaluation case.

This never labels restaurants automatically. Verify facts independently and fill
answerable/relevant_ids/reviewer fields before running review_quality_gate.py.
No network requests, provider credentials, prompts or images are transmitted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from savoroute.live.contracts import LiveDiscoveryInput, LiveDiscoveryOutput
from savoroute.live.validation import _safe_url


def prepare(case_id: str, request: dict, response: dict) -> dict:
    request = dict(request)
    request["consent_remote_processing"] = True
    validated = LiveDiscoveryInput.model_validate(request)
    result = LiveDiscoveryOutput.model_validate(response)
    if (validated.city.casefold() != result.requested_city.casefold()
            or validated.cuisine.casefold() != result.requested_cuisine.casefold()):
        raise ValueError("request and response city/cuisine do not match")
    results: list[dict[str, str]] = []
    for web in result.web_results:
        if _safe_url(web.source_url) is None:
            raise ValueError("Unsafe source URL in captured response")
        stable = hashlib.sha256((web.name + "\n" + web.city + "\n" + web.source_url).encode()).hexdigest()[:20]
        results.append({
            "id": "web-" + stable, "name": web.name, "city": web.city,
            "region": web.region, "country": web.country, "cuisine": web.cuisine,
            "source_url": web.source_url,
        })
    # Catalog entries remain different evidence types; avoid conflating their
    # source tags with public-web review. The measured beta ranking is web-only.
    return {
        "id": case_id, "request": validated.model_dump(exclude={"consent_remote_processing"}),
        "review_status": "unreviewed", "reviewed_by": "", "reviewed_at": None,
        "reviewer_notes": "", "answerable": None, "relevant_ids": None,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists. Never overwrite human annotations")
    row = prepare(args.case_id,
                  json.loads(args.request.read_text(encoding="utf-8")),
                  json.loads(args.response.read_text(encoding="utf-8")))
    dataset = {"dataset_type": "real_captured_unreviewed", "cases": [row]}
    args.output.write_text(json.dumps(dataset, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(f"Unreviewed case {args.case_id} saved; human labels still required")


if __name__ == "__main__":
    main()
