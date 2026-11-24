# SavoRoute controlled-beta data handling (draft — legal/operator review required)

This document explains the intended behavior of the provided beta implementation;
it is **not** a legally approved privacy notice or an assertion about third-party
retention. Do not publish it as a final policy without review and deployment details.

## Inputs, purposes and disclosure

- Ordinary catalog browsing uses server-side recorded metadata; it does not need
  an external AI request. Browser URLs may reflect selected search filters.
- The optional AI feature sends the user's submitted prompt and/or transformed
  food photograph to the configured external provider **only after explicit consent**.
- Optional live restaurant discovery sends the submitted search preferences,
  cuisine and selected municipalities to the external web-search provider after
  explicit consent. Returned leads link to public websites.
- SavoRoute marks web-derived business claims as unverified, even when a human
  reviewer has inspected a cited source; opening hours, menus, dishes, allergy
  safety and restaurant operation are not guaranteed.
- External AI/search services apply their own processing and retention terms.
  The API request sets `store: false`; this alone does not establish zero
  provider-side retention. Consult the provider's current terms.

## Local retention and operational logging

- The app does not intentionally store text prompts, uploaded photographs,
  provider responses, access credentials or individual search histories.
- The controlled-beta SQLite database stores daily attempt totals and HMAC
  pseudonyms of request client addresses for short-lived, fixed-minute quotas.
  This is NOT anonymous data. It may be personal data and must be protected.
- The beta operational log records only request category, method, response
  status, elapsed time and a generated correlation identifier. It deliberately
  excludes raw paths, query strings, source URLs, IP addresses, request bodies,
  API keys, access tokens and image data.
- Proxy basic-auth runs at the HTTPS edge. The edge's own diagnostic logs,
  TLS logs and host/journald retention must be audited and configured before
  real use; this repository cannot control host-wide logging.
- Human review records contain public business names, sources, and reviewer
  identifiers/notes. Keep files in restricted storage and avoid including
  user-supplied private queries.

## Operator obligations before invitations

Provide a contact email, hosting country, identified data controller/operator,
retention timetable for backups and logs, deletion and access-request process,
external provider disclosures, breach handling and an applicable legal basis.
Do not invite minors or collect sensitive dietary/medical details without an
appropriate separately reviewed policy. Review accessibility and privacy laws
for the deployment jurisdiction. Do not commit secrets or private review data.

## User requests, deletion and service limits

Users should be able to contact the operator to request information or deletion
where applicable; publish the actual contact route at launch. The provider and
host may retain data independently. The app cannot attest to downstream deletion
or real-time accuracy of restaurant information.
