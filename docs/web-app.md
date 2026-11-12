# Savoroute v0.14.0 — Local-first web application

## Quick start

```bash
conda activate savoroute
python -m pip install -e ".[api,dev,notebooks]"
savoroute web serve --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`. The same server serves `/docs`, `/openapi.json`, and existing `/v1` endpoints. No Node installation, API key, GPU, network fetch, model download, JavaScript build or account is needed for the bundled fictional catalog. Press `Ctrl+C` in the server terminal to stop.

To use your imported real OSM snapshot:

```bash
savoroute web serve \
  --catalog data/generated/real-pilot/catalog.json \
  --host 127.0.0.1 --port 8001
```

The selected catalog is **loaded at server startup**, not requested from the browser. If port 8000 is already occupied, stop the old server or choose an unused port. Check that the dataset badge says the imported catalog and that the item list contains OSM source references rather than `synthetic_demo`.

## Browser behavior

- **Discover:** enter a query; choose either existing BM25 search (`POST /v1/search`) or catalog-backed preference-aware recommendations (`POST /v1/recommend`). The browser does not reinterpret the returned scores.
- **Hard constraints:** kind, cuisine, location, required dietary tags, and maximum price tier. These are passed to the server's existing `FilterInput`; missing metadata must not be assumed to satisfy a requested constraint.
- **Soft preferences:** preferred cuisines and dietary tags, emphasis in the interval [0, 1], and locally hidden item IDs for recommendations. These map to `PreferencesInput`; scores are ranking utilities, not probabilities.
- **Explore catalog:** read-only paginated `GET /v1/items` with the active filters; next and previous pages. Clicking a card fetches `GET /v1/items/{item_id}` for details.
- **Provenance:** show original source where supplied, catalog fields, retrieval source ranks, and recorded evidence/explanations. Unknown location, tags, or price are displayed as unknown; they are not invented. External source URLs are limited to HTTP(S) and open with `rel="noopener noreferrer"`.
- **Authentication:** the optional Access control sends a configured key to `/v1` in the `X-API-Key` request header. It is held in a JavaScript variable only; refresh or close the tab to clear it. The HTML and static assets themselves are public; catalog data remains protected by the existing HTTP v1 middleware.
- **Errors:** unavailable API, permission failures, no eligible items, and no matching records are differentiated. Requests have cancellation on newer searches and bounded input lengths.

## Software architecture

```
Browser HTML/CSS/JavaScript (packaged and served by FastAPI)
          |
     same-origin /v1
          |
  HTTP contracts + API key middleware
          |
     DiscoveryService
          |
  immutable catalog + retrieval/ranking/recommendation
```

The MCP server reuses the HTTP adapter in-process; the browser uses ordinary HTTP. Neither has an independent recommendation algorithm. The UI requires no third-party scripts, fonts, analytics, or CDNs. Frontend dependencies are intentionally zero.

## Tests

```bash
python -m pytest -q
python -m ruff check src tests scripts
python -m pip check
node --check src/savoroute/web/static/app.js
node --check src/savoroute/web/static/api.mjs
node --test tests/web/*.test.mjs
```

Node 22 is used **only for frontend contract tests**, not required to install or run the web app. CI runs both the Python and Node suites. Optional FAISS/MCP native dependencies have their own test requirements.

## Known limitations and honest claims

The UI reads saved catalog metadata. An OpenStreetMap record may have missing or stale cuisine, menus, contact information, images, prices, current status, or location. The UI does not provide verified opening hours, safety or allergen guarantees, live availability or reservations. Retrieval scores and source attribution are not guarantees of relevance. The independent OSM pilot prepared in v0.11.0 still requires real human judgments; browser functionality must not be presented as a real-world evaluation result.

This is **not a production deployment guide**. Before publishing the service, review authentication/authorization, TLS, reverse-proxy trust, rate limits, monitoring, cache behavior, provenance permissions, content licensing and compliance.
