# Notebooks

These 21 notebooks demonstrate package behavior using local or fictional fixtures. They are instructional examples, not separate implementations or independent evidence of real-world retrieval quality.

Install the optional notebook environment and open JupyterLab from the repository root:

```bash
python -m pip install -e ".[dev,notebooks]"
jupyter lab
```

| Notebooks | Topic |
| --- | --- |
| `00`–`03` | Catalog basics, lexical search, and synthetic retrieval metrics |
| `04`–`07` | Source extraction, OSM ingestion, identity reconciliation, and identity evaluation |
| `08`–`11` | Local image handling, optional joint embeddings, item-level rank fusion, and persistent vector retrieval |
| `12`–`13` | Relevance review, recommendations, and frozen OSM studies |
| `14`–`16` | HTTP API, local stdio MCP tools, and web interface |
| `17`–`19` | Reviewed source evidence, opt-in visit suggestions, geographic discovery, and local media |
| `20` | Two-reviewer study simulation and query-level statistical analysis |

All notebooks are named `NN_description.ipynb` and can be opened individually. The optional CLIP adapter requires separately installed model dependencies and an available model; the default CI exercises offline paths. Notebooks 12, 13, and 20 simulate reviews with **fictional** labels and do not contain independent human judgments. See the [documentation index](../docs/README.md) for production boundaries and detailed study procedures.
