# Grounded Live Restaurant Discovery (PR #27)

## Scope and guarantees

This increment **extends** SavoRoute. Existing catalog retrieval, MCP, recipes,
image interpretation, ranking, and research routes are not replaced.

Two distinct result classes are presented:

- **Recorded catalog matches:** server-filtered with *recorded* city and cuisine
  tags. Missing city or cuisine metadata fails the filter. A limited, explicit
  `Persian` ↔ `Iranian` alias is supported for the new live discovery workflow;
  broad `Middle Eastern` labels do **not** count as Persian.
- **Web-discovered candidates:** obtained through the optional OpenAI Responses
  `web_search` tool. The backend requires an actual web-search tool call, a
  machine-readable source list, a candidate source URL present in that list,
  an exact city, and an explicitly matching cuisine label before displaying
  any candidate. Each candidate retains a clickable source and the explicit
  status `web_search_source_not_independently_verified`.

**These checks are not independent verification that a source is accurate.**
The model may misinterpret webpage content; sources may be outdated. Do not
present restaurant operating status, exact addresses, menus, availability,
pricing, allergies, or requested-dish availability as verified. The feature
should not be used for safety-critical dietary decisions.

## API contracts

- `GET /v1/live/status`: reports whether live discovery is enabled.
- `POST /v1/live/discover` requires JSON, for example:

```json
{
  "query": "kebab or traditional Iranian food",
  "cuisine": "Persian",
  "city": "Boston",
  "region": "MA",
  "country": "United States",
  "consent_remote_processing": true
}
```

`cuisine` and `city` are **required hard constraints**. For the initial
version, `city` means that city, not a geographical radius or metro area.
Someone asking for "near Boston" should explicitly search Cambridge or
another nearby city separately. User text is treated as untrusted context.

The response contains separate `catalog_results` and `web_results` arrays,
never a combined ranking. If no sourced candidate is found, both arrays may
be empty and the UI must say so rather than presenting unrelated restaurants.

## Local setup

Ensure the PR #26 implementation and its CI correction are already merged to
`main`. Then build PR #27 on a **new** branch. Live web search is disabled by
default even when regular AI interpretation is enabled.

In the same local shell as the server (never in React/README/GitHub):

```bash
export SAVOROUTE_AI_ENABLED=1
export SAVOROUTE_LIVE_ENABLED=1
export SAVOROUTE_AI_MODEL=gpt-6.1-terra
export SAVOROUTE_LIVE_MODEL=gpt-6.1-terra
# SAVOROUTE_OPENAI_API_KEY must already be securely exported in this shell.
savoroute web serve --host 127.0.0.1 --port 8000 \
  --catalog data/real/boston-osm-2026-11.json
```

Open `/app/`, enter `Persian` as cuisine and `Boston` as city in the
**Live web discovery** section, explicitly consent, then submit.
Image-to-online discovery: interpret a photo first, choose the proposed cuisine,
and click *Continue to live restaurant discovery*. The city is deliberately
left for the user to choose.

Each live web request **may incur model and web-search charges**. In this
version, an in-memory per-process guard allows 3 live requests per minute per
client address and 1 concurrent search, and upstream calls time out after
35 seconds. This is for development only, **not** a production security,
authentication, or spending-control boundary. No untrusted public deployment
until authentication, persistent/distributed limits, billing caps, network
protections, monitoring and privacy review are in place.

## Technical safety boundaries

- No external source URL is fetched by SavoRoute's backend (avoids SSRF).
- Only HTTPS source links returned by the actual web tool are shown.
- Model-proposed URL text absent from tool-source metadata is discarded.
- No live search results are ingested into or treated as verified catalog data.
- Client cannot select provider model, override the search tool or access the API key.
- `store: false`, explicit per-request consent, and safe error responses are used.
- No AI/model calls are required for CI or unit tests.

## Testing and release gates

Run Ruff, the full Python tests, Node API tests, the Vite production build and
all Playwright tests before merging. A real-provider smoke test (using a funded
API key) is **separately required** to verify that OpenAI web search and
structured responses work together as expected; mocks alone cannot establish
live-provider behavior or restaurant relevance.

The first public beta additionally requires credible provenance and restaurant
relevance evaluation in multiple cities, user testing and production controls.
