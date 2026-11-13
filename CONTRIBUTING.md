# Contributing

Savoroute is a Python package with several interfaces. Retrieval and catalog behavior belong in `src/savoroute/`; the web app, CLI, HTTP API, MCP server, and notebooks must reuse those implementations rather than duplicate ranking logic.

## Set up

Python 3.11 or later:

```bash
python -m pip install -e ".[api,mcp,dev,notebooks]"
```

## Required checks

```bash
python -m pytest -q
python -m ruff check src tests scripts
python -m pip check
node --input-type=module --check < src/savoroute/web/static/app.js
node --input-type=module --check < src/savoroute/web/static/visits-review.js
node --input-type=module --check < src/savoroute/web/static/study-review.js
node --check src/savoroute/web/static/api.mjs
node --test tests/web/*.test.mjs
git diff --check
```

CI also executes all notebooks from the repository root on Python 3.11, 3.12, and 3.13. Run affected notebooks locally when changing their dependencies or examples.

## Change requirements

- Include regression tests for new behavior, failures, boundary inputs, and deterministic ordering where relevant.
- Preserve catalog identities and API contracts unless a deliberate versioned migration is part of the change.
- Distinguish recorded source fields, inferred matches, human-reviewed claims, and verified outcomes. Do not label model output or fictional fixtures as ground truth.
- Document any new optional dependencies, file formats, security assumptions, or operational requirements.
- Keep credentials, downloaded models, real reviewer sheets, personal photo metadata, and generated study artifacts out of Git. Local generated files belong under `data/generated/`.
- Do not introduce third-party images, menus, or datasets without checking redistribution terms and recording attribution.

Use focused pull requests. Record architectural decisions under `docs/adr/`; keep release history in `CHANGELOG.md`, not in the project README. Product and UX priorities are maintained in the [quality plan](docs/product-quality-plan.md).
