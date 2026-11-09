# Development

The library is the source of truth for retrieval and catalog behavior. Notebooks demonstrate package functions, while CLI and future HTTP/MCP interfaces expose the same operations.

## Local checks

```bash
python -m pip install -e ".[dev,notebooks]"
python -m pytest
ruff check src tests scripts
jupyter lab
```

The CI workflow runs tests, Ruff and notebook execution on Python 3.11–3.13. Local notebook changes are checked by running the affected notebook from its first cell using the repository-root working directory.

## Contributions

New package features include tests for validation errors, empty results, deterministic ordering, and applicable constraints. An accompanying notebook illustrates the public API after the implementation is working. Substantial decisions are recorded under `docs/adr/`.

External data and images require documented provenance and redistribution rights. Secrets, personal records, provider responses containing private data, and downloaded model artifacts are excluded from the repository. Evaluation reports identify the dataset, labels, configuration and limitations.
