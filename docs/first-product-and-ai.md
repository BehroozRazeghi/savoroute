# First real SavoRoute product: scope and release gates

## What is shipped in this data-preview change

- Opt-in source-tagged Boston OSM restaurant catalog, collected November 2026.
- Existing React consumer search, filters and navigation continue unchanged.
- Existing read-only local stdio MCP adapter can use the new catalog, with
  `savoroute mcp serve --catalog data/real/boston-osm-2026-11.json`.
- Two **genuine earlier-interface screenshots** in the README. A repeatable
  Chromium capture workflow is included for **current React screenshots**.

## First mobile product experience (recommended next iteration)

A progressive web app or mobile web app is sufficient for the first test:

1. User opens the React app on their phone and types a craving or chooses a photo
   they explicitly want to submit (camera/file picker; no background photo access).
2. For text requests, the existing API searches a source-linked catalog directly;
   this requires no external AI service or API key.
3. For **image** requests, a separate, opt-in **vision provider adapter** sends
   the image to a model selected and paid for by the application operator. It
   returns tentative dish/ingredient labels and a short search query; the user
   can correct the description before SavoRoute searches its catalog.
4. Display only source-backed matching records. Labels inferred by vision
   models are not guaranteed facts, and must not be treated as allergen-safety
   or dietary conclusions. Do not imply exact-image matching without a
   corresponding evaluated visual index.

MCP is complementary: a compatible agent host may analyze an image with its
own model and then call SavoRoute's existing `search_catalog` tool. The current
SavoRoute MCP server is **local stdio, not remotely connectable from any mobile
chat app**. Provider-dependent remote MCP support requires host compatibility,
public transport, authentication, authorization and operational controls.

## Why image analysis is not enabled in this change

A public image-analysis endpoint incurs model costs and processes potentially
private user photos. Before shipping it, implement and test: provider-backed
API calls, secret management (no API keys in browser), explicit opt-in/privacy
notice, restrictive file type/size/decode checks, abuse/rate limits, output
validation, timeouts, retention policy, monitoring, request budgets, and
human-correctable predictions. Never advertise a provider as integrated
without an end-to-end credentialed test against its current API.

## Release gates beyond code unit tests

- Serve HTTPS on a trusted host; keep administrative and research-only tools
  separate from public consumer navigation.
- Confirm dataset attribution and any ODbL derivative-database obligations.
- Revalidate actual operating status, addresses, and closures before stronger
  claims; otherwise prominently label historical data.
- Validate usability on real Android and iOS browser devices, and check
  accessibility, errors, privacy, telemetry, and abuse controls.
- Run Playwright and screenshot capture on the final Git commit and verify
  the images show the released application and expected real catalog.

This is a private / limited public-data preview, **not a production-certified
restaurant directory or deployed photo analyzer**.
