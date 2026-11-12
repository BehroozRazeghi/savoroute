# ADR 0009 — Local MCP stdio as an adapter to shared HTTP contracts

**Status:** Accepted for v0.13.0

## Context

v0.12.0 exposes versioned, bounded catalog discovery and recommendation
contracts through FastAPI. Implementing MCP tools with separately authored
filtering and ranking would introduce divergence and extra security review.

## Decision

- Target **official Python MCP SDK 2.x**, not the legacy 1.x FastMCP import.
- Support **local stdio** only in this milestone; there is no remote MCP HTTP
  listener and no model-controlled connector configuration.
- Register six read-only MCP tools. Do not expose ingestion, filesystem writes,
  URL fetches, arbitrary SQL, model downloads, or code execution.
- Route MCP tool calls via an in-process ASGI client to the existing HTTP
  application and its Pydantic request/response contracts; do not open sockets.
- Construct and validate catalog and index once at startup. Only the process
  operator may select paths. Return the same source attribution, filters,
  ranking evidence, and limitations as the HTTP API.
- Treat MCP read-only annotations as hints; actual read-only restrictions are
  achieved by the implementation and static tool surface.

## Alternatives considered

- **Duplicated MCP business logic:** rejected due to behavioral drift.
- **MCP as an external HTTP proxy:** rejected because it would require a
  separately running web service and introduce unnecessary network exposure.
- **Public Streamable HTTP immediately:** deferred until authentication,
  origin/host handling, rate limiting and data-access policy are specified.

## Consequences

The MCP extra also installs FastAPI, Pydantic and HTTPX; base Savoroute users
do not acquire those dependencies. A small in-process request overhead buys
exact contract parity. The SDK is required for protocol checks and CI. No
empirical relevance accuracy is implied by tests against synthetic data.
