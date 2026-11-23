# Consumer search and discovery — PR 2

**Scope:** `/app/` search, filters and navigation state. The existing `/`, HTTP
v1 search, recommendations, retrieval mathematics and local MCP protocols are
not changed by this milestone.

## Product behavior

- `/app/` opens with the configured catalog's first nine restaurant records.
  Selecting Recipes switches kind without requiring a search query.
- Search text, kind, recorded city, cuisine, maximum recorded price tier, and
  page are shareable via `?q=...&kind=...&city=...&cuisine=...&price=...&page=...`.
  Back/Forward and refresh restore those selections. No user account or tracking
  service is required.
- The city selector includes **only `item.city`** values from the active catalog,
  not address substrings or guessed municipalities. Cuisine options are
  source-recorded; names are case-folded for unique facet options. Price tiers
  are category limits, **not live restaurant prices**.
- `GET /v1/facets?kind=restaurant|recipe` reports source-recorded values and
  source-record counts; the response is calculated once at application startup.
  The existing API authorization applies. The API does not verify those facts.
- Browsing uses `GET /v1/items` with backend filters, `limit=9`, and offset
  pagination. The total comes from the backend's filtered catalog.
- Text queries use existing BM25 `POST /v1/search` with hard filters and
  `limit=100`. The API has no ranked-search offset or match count. UI pages
  only the returned top 100, **without reranking**. When the limit is reached,
  it labels the cap explicitly; it does not claim to know the full match count.
- Browser requests are aborted when constraints change. The UI supports
  loading indicators, no-result explanations, bounded retry, and status
  announcements for assistive technologies.

## Boundaries

- A source-recorded tag or price category is not a validated dietary,
  allergy-safety, current-price, or booking claim. Unknown fields do not satisfy
  an explicit filter. Fictional catalog entries stay visibly labeled.
- Browser requests remain relative to same-origin `/v1/`; consumer secrets,
  externally hosted menu images, accounts, and agent actions are out of scope.
- Initial metadata and facet lists may be unavailable independently. The
  current UI still supports browsing, but cannot offer recorded city choices
  when `/v1/facets` is unavailable.
- The interface is a pre-beta local application. WCAG conformance, usability,
  verified restaurant data, and production reliability require separate audits.

## Verification

From the repository root with Python 3.11+ and Node 22.12+:

```bash
python -m pip install -e ".[api,dev]"
python -m pytest -q
python -m ruff check src tests scripts
node --test tests/web/*.test.mjs
cd webapp
npm ci
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e
```

The Playwright tests cover URL restoration, source-recorded filters, recipe
switching, browser history, API-backed pagination, retry and 320px overflow.
Do not merge the PR until all Python, TypeScript/Vite, and Playwright CI jobs pass.

## Developer integration

PR 2 adds a read-only `GET /v1/facets` response. Other API wire contracts remain
backward compatible; search results and scores are unchanged. The existing
FastAPI `/app/` production build mount is retained. Do not create a new server
or change the existing catalog data for this milestone.
