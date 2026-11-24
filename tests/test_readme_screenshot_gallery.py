"""Current React screenshots with source-transparent real-provider or form-only modes."""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT / "docs/screenshots"
MOBILE_VIEWS = (
    "consumer-mobile-search.png",
    "consumer-mobile-filters.png",
    "consumer-mobile-results.png",
    "consumer-mobile-ai-discovery.png",
    "consumer-mobile-live-discovery.png",
)


def test_readme_uses_desktop_first_gallery_with_feature_viewports():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    begin = "<!-- SCREENSHOTS_BEGIN -->"
    end = "<!-- SCREENSHOTS_END -->"
    assert readme.count(begin) == 1 and readme.count(end) == 1
    gallery = readme.split(begin, 1)[1].split(end, 1)[0]
    assert "#### Desktop application" in gallery
    assert "#### Mobile search and browsing" in gallery
    assert "#### AI-assisted and live discovery" in gallery
    assert "| Search | Filters | Catalog results |" in gallery
    assert "docs/screenshots/consumer-desktop-real.png" in gallery
    assert "docs/screenshots/consumer-mobile-real.png" in gallery
    assert gallery.index("consumer-desktop-real.png") < gallery.index("| Search |")
    assert "| React desktop | React mobile |" not in gallery
    for filename in MOBILE_VIEWS:
        assert f"docs/screenshots/{filename}" in gallery


def test_mobile_viewport_pngs_are_matching_real_chromium_capture_sizes():
    for filename in MOBILE_VIEWS:
        path = SCREENSHOTS / filename
        assert path.is_file(), f"Run (cd webapp && npm run screenshots) to generate {filename}"
        with Image.open(path) as screenshot:
            assert screenshot.format == "PNG"
            assert screenshot.size == (390, 844)
    for filename, expected_width in (
        ("consumer-desktop-real.png", 1440),
        ("consumer-mobile-real.png", 390),
    ):
        path = SCREENSHOTS / filename
        assert path.is_file(), f"Missing full-page screenshot: {filename}"
        with Image.open(path) as screenshot:
            assert screenshot.format == "PNG"
            assert screenshot.width == expected_width


def test_capture_has_no_invented_businesses_and_live_is_explicit():
    script = (ROOT / "webapp/scripts/capture-screenshots.mjs").read_text(encoding="utf-8")
    assert "SAVOROUTE_AI_ENABLED: '0'" in script
    assert "SAVOROUTE_LIVE_ENABLED: '0'" in script
    assert "SAVOROUTE_OPENAI_API_KEY: ''" in script
    assert "const liveMode = args.includes('--live')" in script
    assert "SAVOROUTE_OPENAI_API_KEY in this terminal" in script
    assert "consent" in script
    assert "page.waitForResponse" in script
    assert "web_results.length === 0" in script
    assert "DEMO Persian Restaurant" not in script
    assert "example.org/demo-only" not in script
    assert "installDemoRoutes" not in script
