#!/usr/bin/env python3
"""Optional real-Chromium SavoRoute UX smoke test (offline, via FastAPI TestClient).

Install Playwright and a compatible Chromium separately. This does NOT exercise
browser HTTP transport: it mounts packaged assets in a real DOM and routes the
same-origin browser fetch bridge to FastAPI TestClient, avoiding network access.

Usage: PYTHONPATH=src python scripts/browser_smoke.py --screenshots /tmp/savo-ui
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from savoroute.api.app import create_app


def main() -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit("Optional browser check requires: pip install playwright") from exc

    root = Path(__file__).resolve().parents[1]
    assets = root / "src/savoroute/web/static"
    html = (assets / "index.html").read_text(encoding="utf-8")
    # Strip network-referenced tags; inject their EXACT packaged bytes below.
    html = re.sub(r'<link rel="stylesheet"[^>]+>', "", html)
    html = re.sub(r'<script type="module"[^>]+></script>', "", html)
    api = re.sub(r"\bexport\s+(?=(?:async\s+)?(?:class|function|const|let))", "",
                 (assets / "api.mjs").read_text(encoding="utf-8"))
    app = re.sub(r"^import .* from './api.mjs';\n", "",
                 (assets / "app.js").read_text(encoding="utf-8"))

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--browser", default="/usr/bin/chromium")
    parser.add_argument("--source-facts", type=Path, help="optional catalog-bound source observations")
    parser.add_argument("--catalog", type=Path, default=root / "data/generated/real-pilot/catalog.json")
    parser.add_argument("--recipe-notes", type=Path, help="optional catalog-bound recipe instructions")
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    with TestClient(create_app(catalog_path=args.catalog,
                                   source_facts_path=args.source_facts,
                                   recipe_notes_path=args.recipe_notes)) as client:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True, executable_path=args.browser, args=["--no-sandbox"],
            )
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                failures = []
                page.on("pageerror", lambda error: failures.append(str(error)))

                def handle_request(_source, url, options):
                    response = client.request(
                        options.get("method") or "GET", url,
                        content=options.get("body"), headers=options.get("headers") or {},
                    )
                    return {"status": response.status_code, "body": response.text,
                            "headers": {"Content-Type": response.headers.get(
                                "Content-Type", "application/json")}}

                page.expose_binding("savorouteTestRequest", handle_request)
                page.set_content(html, wait_until="domcontentloaded")
                page.add_style_tag(content=(assets / "styles.css").read_text(encoding="utf-8"))
                page.add_script_tag(content="""window.fetch = async (path, options={}) => {
                  const r = await window.savorouteTestRequest(path, {
                    method: options.method || 'GET', headers: options.headers || {}, body: options.body
                  });
                  return new Response(r.body, {status: r.status, headers: r.headers});
                };""")
                page.add_script_tag(content=api + "\n" + app)
                page.wait_for_function("document.querySelectorAll('#catalog-list article').length === 9")
                catalog_count = client.get('/v1/meta').json()['catalog_items']
                assert page.locator("#catalog-summary").inner_text().startswith(f"{catalog_count} records")
                if args.screenshots:
                    page.screenshot(path=str(args.screenshots / "desktop.png"), full_page=True)
                page.locator("#filter-location").fill("Boston")
                page.locator("#search-query").fill("Italian")
                page.locator("#search-submit").click()
                page.wait_for_function("document.querySelectorAll('#results-list article').length >= 2")
                assert "results" in page.locator("#result-count").inner_text()
                assert "Boston" in page.locator("#results-list").inner_text()
                if args.screenshots:
                    page.screenshot(path=str(args.screenshots / "results.png"), full_page=True)
                # Side-by-side comparison uses only actual response fields.
                page.locator("#results-list .compare-toggle").nth(0).click()
                page.locator("#results-list .compare-toggle").nth(1).click()
                assert page.locator("#compare-bar").is_visible()
                page.locator("#compare-open").click()
                assert page.locator(".compare-table tbody tr").count() == 7
                if args.screenshots:
                    page.screenshot(path=str(args.screenshots / "comparison.png"))
                page.locator("#compare-close").click()
                page.locator("#compare-clear").click()
                assert not page.locator("#compare-bar").is_visible()
                page.locator("#results-list .link-button").first.click()
                page.locator("#dialog-title").wait_for()
                assert "City evidence" in page.locator("#dialog-content").inner_text()
                page.locator("#close-dialog").click()
                # City rejection must not become a substring match.
                page.locator("#filter-location").fill("Cambridge")
                page.locator("#search-submit").click()
                page.wait_for_function("document.querySelector('#result-count').textContent.includes('0 results') && document.querySelector('#results-list .empty-state')")
                assert "No matches" in page.locator("#results-list").inner_text()
                page.locator("#filter-location").fill("Boston")
                page.locator("#advanced-filters summary").click()
                assert page.locator("#advanced-filters").get_attribute("open") is not None
                page.locator("#filter-price").select_option("1")
                page.locator("#search-submit").click()
                page.wait_for_function("document.querySelector('#result-count').textContent.includes('0 results') && document.querySelector('#results-list .empty-state')")
                assert "No matches" in page.locator("#results-list").inner_text()
                page.locator("#reset-filters").click()
                assert page.locator("#filter-location").input_value() == ""
                # Preset terms trigger a real API call; filter selection reflects mode.
                page.locator('[data-kind="restaurant"]').click()
                assert page.locator('#filter-kind').input_value() == 'restaurant'
                page.locator('[data-example="Italian"]').click()
                page.wait_for_function("document.querySelectorAll('#results-list article').length >= 2")
                page.locator("#clear-search").click()
                assert page.locator("#search-query").input_value() == ""
                if args.source_facts:
                    observations = json.loads(args.source_facts.read_text(encoding="utf-8"))
                    with_evidence = next(entry for entry in observations["records"] if entry["facts"])
                    with_facts_item = client.get("/v1/items/" + with_evidence["item_id"]).json()
                    page.locator("#filter-location").fill("")
                    page.locator("#search-query").fill(with_facts_item["title"])
                    page.locator("#search-submit").click()
                    page.wait_for_function("document.querySelectorAll('#results-list article').length >= 1")
                    page.locator("#results-list .link-button").first.click()
                    page.wait_for_function("document.querySelector('.source-facts-panel') !== null")
                    assert "Recorded OSM observations" in page.locator("#dialog-content").inner_text()
                    assert "unverified" in page.locator("#dialog-content").inner_text().lower()
                    if args.screenshots:
                        page.screenshot(path=str(args.screenshots / "source-facts.png"))
                    page.locator("#close-dialog").click()
                if args.recipe_notes:
                    assert any(
                        item["title"] == "Red Lentil Soup"
                        for item in client.get("/v1/items?kind=recipe&limit=20").json()["items"]
                    ), "Expected Red Lentil Soup in the recipe catalog"
                    page.locator("#filter-location").fill("")
                    page.locator('[data-kind="recipe"]').click()
                    page.locator('#search-query').fill('lentil')
                    page.locator('#search-submit').click()
                    page.wait_for_function("document.querySelectorAll('#results-list article').length >= 1")
                    page.locator('#results-list .link-button').first.click()
                    page.wait_for_function("document.querySelector('.recipe-notes-panel') !== null")
                    panel = page.locator('.recipe-notes-panel')
                    assert 'Red Lentil Soup' in page.locator('#dialog-title').inner_text()
                    assert 'Preparation' in panel.inner_text()
                    assert 'CC-BY-SA-4.0' in panel.inner_text()
                    assert panel.locator('ol li').count() >= 3
                    if args.screenshots:
                        page.screenshot(path=str(args.screenshots / 'recipe-details.png'), full_page=True)
                    page.locator('#close-dialog').click()
                for width in (320, 375, 768, 1440):
                    page.set_viewport_size({"width": width, "height": 850})
                    assert not page.evaluate(
                        "document.documentElement.scrollWidth > window.innerWidth"
                    ), f"horizontal overflow at viewport width {width}"
                    if width == 375 and args.screenshots:
                        page.screenshot(path=str(args.screenshots / "mobile.png"), full_page=True)
                assert failures == [], f"browser JavaScript exceptions: {failures}"
                print(json.dumps({"result": "PASS", "catalog": catalog_count,
                                  "screen_widths": [320, 375, 768, 1440],
                                  "browser_exceptions": len(failures),
                                  "network_mode": "FastAPI TestClient bridge (offline)"}, indent=2))
            finally:
                browser.close()


if __name__ == "__main__":
    main()
