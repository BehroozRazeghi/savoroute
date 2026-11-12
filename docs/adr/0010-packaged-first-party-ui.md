# ADR 0010 — Package the first web interface with the Python service

Status: accepted for v0.14.0.

## Context

The repository already provides a tested domain service, CLI, versioned HTTP API, and local MCP adapter. A first browser UI should not duplicate retrieval rules or require an unrelated service to run a small local catalog.

## Decision

Use dependency-free, first-party HTML, CSS and browser JavaScript packaged in `savoroute.web` and served at `/` alongside HTTP v1. Add an alias `savoroute web serve` that calls the same server factory as `savoroute api serve`. Keep the existing API and MCP response contracts unchanged.

All dynamic data is fetched via bounded same-origin `/v1` requests. Presentation code uses DOM `textContent` rather than interpolating catalog content into HTML; only `http:` and `https:` provenance URLs become clickable. Store an optional API key in browser memory, never in local storage, source code, query strings or cookies. The homepage has a restrictive CSP without inline scripts, styles or remote assets. The browser cannot change startup catalog/index paths or initiate data ingestion/model downloads.

## Alternatives considered

- **React/Vite split app:** appropriate for a larger consumer product, but adds a Node build, artifact deployment/version skew, and client routing complexity now. We can migrate later while preserving API contracts.
- **HTML templates per query:** adds server-rendered view state and a second Python presentation layer. Less useful for in-page filters and evidence dialogs.
- **Direct MCP-to-browser bridge:** introduces an unnecessary protocol/client requirement; the existing HTTP API is the browser interface.

## Consequences and limitations

This is intentionally **local-first**. It is not a hardened public deployment: an API key is not a substitute for TLS, rate limits, authentication/authorization, secret management, monitoring, abuse limits, or CSP review under a reverse proxy. The public HTML shell remains reachable even with an API key; all catalog data routes still require it. No image gallery is fabricated when a catalog has no trusted image URLs. No claims are made about freshness, verified cuisine, food allergies, reservations or empirical retrieval quality.
