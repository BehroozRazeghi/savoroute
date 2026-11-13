# Executable notebooks

These notebooks demonstrate the package's public interfaces with local fixtures. They are not independent implementations or evidence of real-world retrieval quality. Run from the repository root after installing `.[dev,notebooks]`.

| Notebook | Subject |
| --- | --- |
| 00 | Catalog quickstart |
| 01 | Schema validation and provenance |
| 02 | Lexical retrieval and filters |
| 03 | Retrieval metrics |
| 04 | Structured text ingestion |
| 05 | OSM import and extraction checks |
| 06 | Source identity and updates |
| 07 | Identity matching evaluation |
| 08 | Local image ingestion |
| 09 | Cross-modal vector index |
| 10 | Item-level rank fusion |
| 11 | Persistent vector backends and synthetic latency |
| 12 | Relevance review and recommendations |
| 13 | Frozen OSM study setup |
| 14 | Read-only HTTP API |
| 15 | Local read-only MCP tools |
| 16 | Browser application |
| 17 | Reviewed catalog evidence |
| 18 | Opt-in visit suggestions |
| 19 | Nearby search and reviewed local media |
| 20 | Query-level statistical evaluation |

```bash
python -m pip install -e ".[api,mcp,dev,notebooks]"
jupyter lab
```

The CI workflow executes all 21 notebooks offline on three supported Python versions. Model-backed inference and actual human adjudication are not part of these demonstration notebooks.
