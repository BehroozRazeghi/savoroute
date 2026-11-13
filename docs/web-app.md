# SavoRoute browser application (v0.21.1 developer preview)

## Run

```bash
python -m pip install -e '.[api,dev]'
savoroute web serve --host 127.0.0.1 --port 8000
# Optional saved Boston OSM pilot (requires separately generated, Git-ignored data)
savoroute web serve --catalog data/generated/real-pilot/catalog.json --port 8001
```

The catalog is selected at **server startup** and cannot be replaced by a browser request. `http://127.0.0.1:8001/` provides the same versioned FastAPI read-only service as `/v1/search`, `/v1/recommend`, `/v1/items`, and `/v1/nearby`. No Node, CDN, remote font or third-party script is required to run the page.

## Interaction model

1. **Search first.** Enter a craving and hit Enter or Find matches. Preset examples populate the query and issue an actual request. The page begins with no fabricated results; users can browse the saved catalog below.
2. **Choose an intent.** All food, Dine out, and Cook at home set the existing `kind` constraint. Choosing a new intent while a query is present reruns it. This is not a language-model inference of intent.
3. **Add the known city.** The city/location input sends the compatible exact `location` filter to HTTP v1. `Boston` matches source-recorded `city=Boston`; an unknown city does not match just because the street address or snapshot name mentions Boston. This is *not* a radius search.
4. **Reveal advanced filters only when needed.** Required cuisine, required dietary tags, optional maximum price tier and the existing search/recommend mode live in a native disclosure. Missing price/dietary information cannot satisfy strict constraints. Preferences are soft and applied only in recommendation mode.
5. **Inspect, exclude, compare.** The server supplies catalog results and retrieval evidence. Cards use CSS-decorative artwork labeled **not item photography**, because the Boston pilot has no licensed first-party photos. View details loads item fields, reviewed source references and separately packaged local images if present. An optional browser-only comparison tray holds at most three returned items; it makes no ratings or prices up.
6. **Explore directly.** The original paginated catalog (nine items per page) and the opt-in coordinate-based Nearby feature remain accessible below search. Nearby still needs a matching OSM source snapshot at server startup and reports straight-line distance only.

## Evidence and privacy constraints

- Catalog descriptions, cuisines, addresses, tags and prices are recorded data. Generic OSM descriptions are not restaurant descriptions and should not be promoted as such. Unknown is an informative state.
- Retrieval scores are *not* relevance probabilities. Recommendations do not imply available tables, up-to-date menus, prices, hours or food allergy safety.
- Source URLs are vetted by the existing HTTP(S) allowlist and rendered as independent links; user-provided text is written through DOM `textContent`, not injected HTML.
- The API key (when enabled) is held only in this page's JavaScript variable and sent in `X-API-Key`, never appended to source links, URLs or browser storage. The HTML/CSS/JS shell is public; `/v1` data can be key protected.
- The comparison list, exclusion list and selected preferences are *tab-local*; there are no accounts, saved bookmarks or payment functionality.
- The HTTP API is unchanged and no autonomous LLM agent, live reservation integration or remote MCP service is introduced by this UI milestone.

## Test

```bash
PYTHONPATH=src python -m pytest -q
node --check src/savoroute/web/static/app.js
node --test tests/web/*.test.mjs
# Optional: requires locally installed playwright and Chromium, no network
PYTHONPATH=src python scripts/browser_smoke.py --screenshots /tmp/savoroute-ui
```

The optional Chromium check uses the real browser DOM and packaged HTML/CSS/JS, with the browser's fetch bridged to the actual FastAPI TestClient. It tests search, city rejection, unknown-price exclusion, result detail, comparison and 320/375/768/1440 px widths. It does **not** verify real socket transport, CDN/network behavior, Lighthouse scores, screen-reader behavior or production readiness.

## Remaining work

Prioritize verified geographic boundary imports, restaurant and recipe coverage, licensed and reviewed image assets, better evidence and current menus, independent relevance labeling, cross-browser QA, and deployment design. Neither improved visuals nor passing browser tests establish product-market fit.


### Source provenance panel (v0.20.0)

Run `savoroute web serve --catalog <your-catalog.json> --source-facts
<your-source-facts.json>` to opt in to a date-stamped, ODbL-attributed OSM
source-observation panel within item details. Values remain unverified and
never imply real-time opening, dietary safety or booking availability. Source
links are opened only on user action. See
`docs/data-quality-and-source-facts.md` for reproduction and limitations.

### Source-linked recipe details (v0.21.0)

For a combined catalog created by `savoroute quality recipes-build`, opt into `--recipe-notes` **using the sidecar created from that exact catalog digest**. Recipe detail panels show ingredient lists, preparation steps, source revision, CC BY-SA 4.0 license, attribution and an unverified-review status. Restaurant cards do not display recipe steps; recipe cards no longer show meaningless restaurant city/price fields. The browser intentionally does not render unlicensed third-party recipe images. See `docs/recipe-curation-m4.md` for source and publication limitations.

## Other opt-in local workflows

- **Reviewed media and menus:** pass a compatible catalog and reviewed evidence/media sources at server startup, subject to source rights and manual verification; see [reviewed media and geographic discovery](geography-and-reviewed-media.md). Local images are not silently replaced with unlicensed external images.
- **Private visit suggestions:** the separately served `/visits-review` page reviews explicitly user-selected local metadata, not a background scan or an automatic update of the user's personal history. See [opt-in visit discovery](opt-in-visit-discovery.md).
- **Independent study reviews:** the `/study-review` page supports an explicitly initiated, local labeling workflow; simulated or incomplete labels are not evidence of real-world ranking performance. See [statistical relevance study](statistical-relevance-study.md).

These workflows are not a deployed autonomous agent or proof of commercial product readiness.
