# MCP server v0.13.0 — local, read-only catalog access

Savoroute exposes six **read-only** Model Context Protocol tools using the
[official MCP Python SDK v2](https://github.com/modelcontextprotocol/python-sdk).
The MCP server uses **stdio**: an MCP client launches a local Savoroute process
and exchanges protocol messages on standard input/output. There is **no**
network-facing MCP endpoint in v0.13.0.

## Install and run

From a checked-out repository:

```bash
python -m pip install -e ".[mcp,api,dev,notebooks]"
savoroute mcp serve
# The terminal stays quiet and occupied: stdio transport is awaiting an MCP client.
# Ctrl+C stops it. Do not send shell commands to its stdin.
```

To use your previously created real OSM catalog:

```bash
savoroute mcp serve --catalog data/generated/real-pilot/catalog.json
```

The catalog is loaded and validated **once at startup**. Optional vector
retrieval requires an index previously produced by Savoroute and a matching
catalog; neither can be chosen or changed by tool calls:

```bash
savoroute mcp serve \
  --catalog data/generated/m2b/media/catalog.json \
  --index data/generated/m2b/vectors.json
```

This version does not load an embedding model in the server. If an index is
configured, callers may supply a bounded, precomputed, compatible query vector.
Without a vector, rank/recommend default to BM25-only item rankings. See
[HTTP API](http-api.md) for the same fusion rules and restrictions. No model
downloads, inference, image upload, restaurant reservations, OSM fetching, or
filesystem writes are exposed as MCP tools.

### MCP host configuration (example)

Most local MCP hosts accept a JSON configuration of the following *general*
shape (use the exact format documented by your host):

```json
{
  "mcpServers": {
    "savoroute": {
      "command": "/home/YOU/anaconda3/envs/savoroute/bin/savoroute",
      "args": [
        "mcp", "serve",
        "--catalog", "/home/YOU/my_github/savoroute/data/generated/real-pilot/catalog.json"
      ]
    }
  }
}
```

Replace `/home/YOU/` with your actual home directory and use the Savoroute
executable in your active environment (`command -v savoroute`). Use **absolute
catalog paths** because the MCP host may launch the subprocess from an
unrelated working directory. The path is chosen by the host/operator, not
accepted from the language model. Only connect MCP hosts you trust to read
that catalog: stdio is local access, not authentication.

## Available tools

| MCP tool | Arguments | Shared endpoint |
| --- | --- | --- |
| `catalog_metadata` | none | `GET /v1/meta` |
| `list_catalog_items` | filters, offset, limit | `GET /v1/items` |
| `get_catalog_item` | item_id | `GET /v1/items/{item_id}` |
| `search_catalog` | query, filters, method, limit | `POST /v1/search` |
| `rank_catalog` | query, filters, weights, optional query_vector, RRF controls | `POST /v1/rank` |
| `recommend_catalog` | query, filters, preferences, optional query_vector, RRF controls | `POST /v1/recommend` |

Tool arguments use the same Pydantic validation contracts as HTTP v1. The MCP
SDK also advertises type constraints in tool schemas. All tools are marked
read-only and closed-world, but these annotations are advisory, **not** a
security boundary. API errors become MCP tool errors. The server does not
expose item update, file access, execution, remote search, or network fetch
capabilities.

### In-memory SDK integration test

With the MCP extra installed, this Python snippet exercises the actual SDK v2
client/server protocol without opening a port:

```python
import asyncio
from mcp import Client
from savoroute.mcp.server import create_server

async def main():
    async with Client(create_server()) as client:
        tools = await client.list_tools()
        print([tool.name for tool in tools.tools])
        result = await client.call_tool("search_catalog", {
            "query": "spicy tofu noodles", "limit": 3,
        })
        print(result.structured_content)

asyncio.run(main())
```

Notebook `15_mcp_readonly_tools.ipynb` demonstrates the in-process service
bridge and optional protocol integration.

## Design and safety boundaries

1. **Shared behavior:** The MCP adapter runs the existing FastAPI application
   with `httpx.ASGITransport` *in-process*. The service owns retrieval,
   filtering, ranking, recommendations, and response contracts. MCP does not
   have an independent implementation.
2. **No outbound HTTP:** The host name `savoroute.internal` is a local ASGI
   base URL for request routing; it is not resolved through DNS or connected
   over a socket. The adapter makes no remote data requests.
3. **Fixed inputs:** Operators select the catalog/index on process startup.
   User calls cannot provide paths, URLs, model names, or arbitrary endpoints.
4. **Limits:** Query length, pagination, filters, exclusions, vector lengths,
   and RRF options are validated by the existing Pydantic contracts. Errors
   are sanitized and do not echo arbitrary rejected payloads.
5. **Provenance:** Return values include the catalog source and the existing
   limitations. BM25/RRF scores are not calibrated probabilities. No claims of
   dietary or allergen safety, current opening hours, live availability, or
   booking support are made.
6. **Deployment:** Stdio is intentionally local. Remote Streamable HTTP would
   require explicit authentication/authorization, transport security,
   origin/host validation, abuse prevention, operational monitoring and
   deliberate data-exposure policy. It is not implemented by this milestone.

## Tests and release checks

```bash
python -m pip install -e ".[mcp,api,dev,notebooks]"
python -m pytest -q
python -m ruff check src tests scripts
python -m pip check
```

CI installs the `mcp` extra on Python 3.11, 3.12 and 3.13 and runs a real
in-memory MCP v2 protocol test. If the `mcp` extra is not installed locally,
that test is skipped; the core in-process bridge tests still run. An installed
MCP SDK is required before claiming end-to-end protocol verification.
