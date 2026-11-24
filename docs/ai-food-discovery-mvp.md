# SavoRoute: opt-in AI food discovery (PR #26)

## Scope and evidence boundary

This PR adds a usable **local/mobile-web** food interpretation flow to the existing
React consumer app, without modifying the SavoRoute retrieval, ranking, catalog,
MCP, or OSM logic. The feature is **disabled by default** and makes **no remote
calls** until an operator configures it and a user explicitly opts in for that
request. The user can type a craving or choose/take a food photo, inspect and
edit the generated search phrase, and deliberately send that phrase to the
existing catalog search endpoint. No AI-generated result is a verified menu
claim or a verified restaurant record.

The provider is an adapter based on the OpenAI **Responses API**. It sends one
short prompt and optionally one downscaled, re-encoded JPEG image, requesting
strict structured JSON. The configured model defaults to `gpt-6.1-terra` and may
be changed using an environment variable after checking support for image input
and structured outputs. This is a **real provider implementation**, but a live
paid invocation requires an operator-provided key; CI uses deterministic mocks.

## Setup for local development

Requirements: Python 3.11+, Node 22.12+, a supported browser, and an OpenAI API
key with billing enabled. AI API usage is separately billed, independent of
ChatGPT subscriptions. Use an operator-owned key in the **server environment**,
never in the React application, Git history, or `webapp/.env`.

```bash
cd ~/my_github/savoroute
conda activate savoroute
python -m pip install -e ".[api,ai,dev]"
(cd webapp && npm ci && npm run build)

# On a local trusted machine only. Do not paste your key into chat, files,
# git commits, or screenshots. Prefer your shell's secure secret manager.
export SAVOROUTE_AI_ENABLED=1
export SAVOROUTE_OPENAI_API_KEY="$(your-secret-manager-command)"
# Optional, defaults to gpt-6.1-terra:
# export SAVOROUTE_AI_MODEL=gpt-6.1-terra

savoroute web serve --host 127.0.0.1 --port 8000 \
  --catalog data/real/boston-osm-2026-11.json
```

Replace the placeholder `your-secret-manager-command` with your local secret
manager; alternatively export the secret manually in your shell without storing
it in a tracked file. **Never substitute a literal string for an actual key in
committed code.**

Open `http://127.0.0.1:8000/app/` on the same machine. The AI component appears
between the hero and catalog browser. The user must separately opt into sending
their request to the external provider; the search phrase can be revised before
searching the catalog. Using the standard browser without setting
`SAVOROUTE_AI_ENABLED=1` keeps local discovery functional and displays an
explicit AI-disabled message.

For a text-only local API smoke test (with consent):

```bash
curl -sS http://127.0.0.1:8000/v1/ai/status
curl -sS http://127.0.0.1:8000/v1/ai/interpret \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"spicy tofu noodles","consent_remote_processing":true}'
```

Avoid leaving test prompts or photos in terminal history if they are sensitive.

## HTTP contracts

- `GET /v1/ai/status`: availability only; does not disclose model, key, or
  provider configuration.
- `POST /v1/ai/interpret`: bounded `application/json` with `prompt` (0–500
  characters), optional raw `image_base64` (JPEG, PNG, WebP), and required
  `consent_remote_processing: true`. At least one of prompt/image is required.
- Structured response: `interpretation.search_query`, `dishes`, `cuisines`,
  `ingredients`, `uncertainties`, and explicit `catalog_verified: false`.
- The AI endpoint **does not call catalog search**. The user must confirm and
  submit the interpretation through the existing UI. No image bytes or prompts
  are included in a result URL unless the user chooses to use a suggested text
  search, in which case only the edited search phrase enters URL state.

Errors: 413 oversized JSON, 415 unsupported media type, 422 invalid image/consent,
429 local process budget/concurrency exceeded, 503 AI disabled or upstream error.
Provider secrets and upstream response bodies are not returned to clients.

## Privacy, safety, and operational limitations

- Photos are validated as actual JPEG/PNG/WebP bytes, checked for dimensions,
  reoriented, resized, re-encoded to JPEG **without EXIF**, and transmitted to
  the configured external model only after explicit opt-in. No source photo is
  saved by the SavoRoute backend. Provider retention and other processing are
  governed by the provider's terms; `store: false` disables Responses storage
  but does **not** guarantee zero provider-side retention.
- The configured provider endpoint is fixed to `https://api.openai.com/v1/responses`;
  no arbitrary URLs, uploaded names, remote tools, or remote catalog access are
  accepted. The model is instructed to treat image/text content as data.
- Maximum request body ~5.8 MB; source image 4 MB; 12 MP source dimensions;
  max processed size 1536 px; provider timeout 25 seconds; 600 output tokens;
  six accepted requests/minute per socket IP; at most two concurrent calls per
  server process. These bounds reduce accidental usage and cost but are **not**
  reliable global cost caps or a substitute for production defenses.
- This first slice is a **local beta**. Do not expose an unauthenticated paid AI
  endpoint to the internet. Before public hosting, add real user/session auth,
  distributed rate limits, upstream billing caps, per-user abuse controls, TLS,
  monitoring, privacy disclosures, and a secure reverse-proxy deployment.
  Existing `SAVOROUTE_API_KEY` protects all `/v1` routes and the current browser
  consumer cannot supply that key; public access requires a separate auth design.
- OSM catalog metadata is neither menu evidence nor proof a restaurant serves
  a suggested dish, or that a restaurant is open. Allergens and dietary safety
  must never be inferred from a food photograph. Failures are reported as
  generic errors rather than fabricated suggestions.

## Tests and deployment gates

```bash
python -m ruff check src tests scripts
python -m pytest -q
node --test tests/web/*.test.mjs
python -m pip check
(cd webapp && npm ci && npm run build && npm run test:e2e)
```

Backend tests use an injected fake provider and mock HTTPS responses; no real API
key or paid request is needed. Browser tests mock AI status and inference routes.
A manual local smoke test with the configured real provider is still required
before calling this an end-to-end live-AI release. Update README screenshots
only from a verified running build using the project's capture workflow.

OpenAI reference: https://developers.openai.com/api/docs/guides/images-vision
and https://developers.openai.com/api/docs/guides/structured-outputs .
