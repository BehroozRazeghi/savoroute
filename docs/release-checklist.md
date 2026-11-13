# Public repository release checklist

This is a code-publication checklist, **not** a production deployment approval.

## Source and metadata

- [ ] The working branch is based on the intended `origin/main` commit; review `git status` and `git diff --stat`.
- [ ] No empty root notebook, checkpoint, generated files, source archives, credentials, raw photos or user records are staged.
- [ ] `README.md`, `CHANGELOG.md`, `pyproject.toml`, and `savoroute.__version__` are consistent.
- [ ] New third-party content has explicit source revisions, attribution, rights terms and a review note.
- [ ] Any generated catalog required for a demonstration is distributed separately or recreated from documented inputs; do not imply ignored `data/generated/` files are present in a fresh clone.

## Validation

```bash
python -m pip install -e ".[api,mcp,dev,notebooks]"
python -m pytest -q
python -m ruff check src tests scripts
node --input-type=module --check < src/savoroute/web/static/app.js
node --test tests/web/*.test.mjs
```

- [ ] Run the browser smoke script where Playwright + Chromium are available: `python scripts/browser_smoke.py --help` for supported arguments.
- [ ] Review all CI jobs on the PR (Python 3.11/3.12/3.13, Node, notebooks); resolve failures before merging.
- [ ] Verify that the app launches using the committed fictional data after a **fresh clone**.

## Limits to disclose

- [ ] The Boston boundary backfill remains outstanding for 41 restaurants until an authoritative polygon is fetched and checked.
- [ ] The three recipe adaptations have not been independently cooked or reviewed for dietary/allergen safety.
- [ ] No production authentication, availability/booking integration, real-data relevance judgments, or production security audit is claimed.

Use a reviewed pull request to merge; delete its head branch only after the merge is confirmed.
