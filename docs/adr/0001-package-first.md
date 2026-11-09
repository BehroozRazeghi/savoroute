# ADR 0001 — One Python implementation

**Status:** Accepted · 2026-11-09

Search, validation, and evaluation are implemented in the installable package. Notebooks import these functions, and the CLI exposes them. Future API and MCP handlers will use application services rather than maintain separate retrieval algorithms.

This adds an installation step to the notebook workflow, but makes interactive lessons and batch execution test the same code. The alternative—copying algorithms into notebooks—was rejected because their behavior would diverge as the project evolves.
