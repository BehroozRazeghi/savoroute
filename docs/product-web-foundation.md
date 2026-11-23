# Consumer web foundation — PR 1

**Status:** source implementation for review; separate from the existing `/` browser UI.

## Scope and design decisions

- `webapp/` is a React 19 + TypeScript + Vite application; no Next.js server, SSR,
  accounts, payments, geolocation, or autonomous-agent actions.
- It uses only the **existing** `GET /v1/meta`, `GET /v1/items`, and `POST /v1/search`.
  No novel ranking logic, menu verification, or new data API is introduced.
- It is served by FastAPI at `/app/` when built and is developed with Vite at
  `http://127.0.0.1:5173/app/`, with a same-origin `/v1` development proxy to
  a local FastAPI instance on port 8000.
- The original `/`, `/assets`, `/docs`, `/study-review`, `/visits-review`,
  `/v1`, and the CLI/MCP contracts are retained without behavioral migration.
- Browser state is ephemeral. Saved lists, shareable detail pages, advanced
  filters, map/list UI, and persistent user state are **out of scope** for PR 1.
- The catalog controls the truth. Fictional entries are labelled explicitly;
  omitted price, safety, source freshness, or reviews are **not** inferred.
- Illustrations are decorative CSS and SVG, never claimed as venue photos.

## Local build and run

Requires Python 3.11+ and Node >=22.12. Run from the repository root:

```bash
python -m pip install -e ".[api,dev]"
(cd webapp && npm install && npm run build)
savoroute web serve --host 127.0.0.1 --port 8000
```

Browse http://127.0.0.1:8000/app/ (consumer) and http://127.0.0.1:8000/
(legacy). With no built `consumer_dist/index.html`, `/app/` returns an
explicit 503; it never silently serves an outdated page. Restart FastAPI after
building because the mount is registered when the app starts.

For live development, use two terminals:

```bash
savoroute web serve --host 127.0.0.1 --port 8000
cd webapp && npm run dev
```

Open http://127.0.0.1:5173/app/. The Vite dev server is local-only. Do not bind
it to an untrusted interface or use it as a public hosting solution.

## Verification

```bash
python -m pytest -q
python -m ruff check src tests scripts
node --test tests/web/*.test.mjs
cd webapp
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e
```

The CI `consumer_web` job independently builds the UI and runs integration and
Chromium tests; the Python matrix still tests the existing application.

## Security and data boundaries

- The browser client only fetches relative `/v1/` paths, sends no stored API key,
  never forwards to third-party hosts, and never displays rejected server input.
- The new shell is suitable only for an unprotected local catalog. An API-key
  protected server returns a visible authorization error, **not** a bypass.
- Static responses are served with strict same-origin CSP, `nosniff`, no-referrer
  and no-framing headers. No external font/image network requests are required.
- Review tools remain local and are not linked into the consumer main navigation.
- For a public launch, separate consumer authentication, operator-only endpoints,
  rate limits, secrets, telemetry consent, data terms and deployment security
  must be designed and tested. This PR makes no production-security claim.

## Packaging and reproducibility

The Vite build output is ignored at `src/savoroute/web/consumer_dist/`. A local
wheel needs `npm run build` **before** `python -m build`. The Python package
includes built HTML/CSS/JS when those files exist; the repository ZIP does not
ship a stale generated bundle.

The PR's CI currently uses `npm install` because the build environment here could
not reach the npm registry to generate and verify a lockfile. Before release,
create and commit `webapp/package-lock.json` from a trusted local `npm install`,
switch CI to `npm ci`, and rerun the build. This is a release gate, not a claim
of dependency-reproducible publishing.

## PR 1 acceptance gate

- Existing HTTP v1 responses, CLI, notebook and MCP behavior remain unchanged.
- Consumer shell supports accessible navigation, actual catalog-backed browsing,
  basic lexical query, details, honest unknown fields, error/empty/loading states.
- Desktop and small mobile browser flows run without horizontal overflow or
  uncaught JavaScript exceptions. Build, typecheck and CI must pass.
- User testing, WCAG 2.2 AA auditing and production Core Web Vitals measurement
  are explicitly deferred; no certification or performance claim is made.
