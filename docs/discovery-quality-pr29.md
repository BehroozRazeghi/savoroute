# PR #29 — SavoRoute discovery quality and explicit geographic coverage

## What this changes

The `/v1/live/discover` API preserves its exact-city default. It now accepts:

```json
{
  "cuisine": "Persian", "city": "Boston", "region": "MA",
  "country": "United States", "query": "kebab",
  "geography_scope": "nearby",
  "nearby_cities": ["Cambridge", "Somerville", "Brookline", "Newton"],
  "consent_remote_processing": true
}
```

- `city` (default) checks just the selected city, as before.
- `nearby` checks **only the additional municipalities the user has explicitly entered**
  in addition to the origin city. Region and country are required in this mode.
  The application offers an *editable* Boston example, not an official metro boundary.
- This is **not radius or travel-time search**. Accurate distance-bounded *web* discovery
  requires verified business coordinates and a geocoding/Places integration; AI-proposed
  coordinates are not sufficient evidence. The pre-existing source-bound OSM `/v1/nearby`
  endpoint remains available for local geometry queries.
- Cuisine is a hard requirement: Persian and Iranian are synonymous for this filter,
  but Middle Eastern, Lebanese and Mediterranean are not accepted substitutes.
- Extra keywords are **soft ranking preferences** based on recorded catalog text or
  web-source title/name. They do not establish that a dish is on a current menu.
- Catalog and web results are filtered independently. Exact name + city + region +
  country matches may be linked to an additional web source rather than listed twice;
  uncertain identities remain separate. Missing city/cuisine or requested jurisdiction
  metadata means no match.
- A web citation means the source URL was returned by the web-search tool, **not**
  that the page's claims, cuisine, dishes, menu, address or operating status were
  independently verified. Do not present web leads as confirmed businesses.
- The same request-level opt-in, bounded input, server-key protection and separate
  live rate guard from PR #27 remain in effect. Paid web queries are **not** invoked
  by the evaluation suite.

## Evaluation: no invented real-world measurements

`data/sample/live_discovery_synthetic_quality.json` contains artificial entities.
It validates the evaluation tool and is NOT a measured restaurant quality score.

```bash
python scripts/evaluate_live_discovery.py \
  data/sample/live_discovery_synthetic_quality.json \
  --require-zero-violations
```

`data/evaluation/live_discovery_100_query_review_template.json` provides 100 *unreviewed*
query candidates across ten cuisines, five location scopes, and cuisine, dish, dietary
and multilingual request styles. Dietary terms remain soft and do not certify safety.
The evaluation command deliberately rejects this file until reviewers have filled in
actual relevance labels and results; the template is not a quality benchmark.

To evaluate actual relevance, independently review 100 representative queries,
including added dietary, multilingual, and genuinely unanswerable cases as needed. For each
query, annotate `answerable`, a set of stable known-relevant result identifiers,
and the actual output records with city/cuisine/citation metadata.

Metrics:

- `precision_at_5`: relevant top-five returned results / (`5 × queries`).
- `success_at_5_answerable`: fraction of answerable queries returning a labeled
  relevant entity in the top five.
- `correct_abstention_unanswerable`: fraction of reviewed unanswerable cases
  returning zero results.
- `hard_constraint_violation_rate`: displayed records violating explicit
  cuisine or city/region/country constraints / displayed records.
- `cited_url_coverage`: displayed records containing a syntactically safe HTTPS
  source URL / displayed records. **Not factual source verification.**

The tool cannot infer missing ground truth or independently verify webpages.
Never report synthetic fixture metrics as real product precision.

## Release gates

1. Ruff + full Python tests; Vite typecheck/build and Playwright suite.
2. At least one **funded, opt-in** API smoke test in exact-city and nearby mode.
3. Human-reviewed real-world relevance and false-positive analysis across cities.
4. No public hosting without authenticated rate limits, spending limits,
   consent/retention review, and monitoring (planned production milestone).
