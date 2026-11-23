"""Real-app README gallery and reproducible viewport screenshot contracts."""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOTS = ROOT / "docs/screenshots"
MOBILE_VIEWS = (
    "consumer-mobile-search.png",
    "consumer-mobile-filters.png",
    "consumer-mobile-results.png",
)


def test_readme_uses_desktop_first_gallery_with_mobile_viewports():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    begin = "<!-- SCREENSHOTS_BEGIN -->"
    end = "<!-- SCREENSHOTS_END -->"
    assert readme.count(begin) == 1 and readme.count(end) == 1
    gallery = readme.split(begin, 1)[1].split(end, 1)[0]
    assert "#### Desktop application" in gallery
    assert "#### Mobile application" in gallery
    assert "| Search | Filters | Restaurant results |" in gallery
    assert "docs/screenshots/consumer-desktop-real.png" in gallery
    assert "docs/screenshots/consumer-mobile-real.png" in gallery
    assert gallery.index("consumer-desktop-real.png") < gallery.index("| Search |")
    # Old two-column gallery caused the huge blank row.
    assert "| React desktop | React mobile |" not in gallery
    for filename in MOBILE_VIEWS:
        assert f"docs/screenshots/{filename}" in gallery


def test_mobile_viewport_pngs_are_real_matching_capture_sizes():
    for filename in MOBILE_VIEWS:
        path = SCREENSHOTS / filename
        assert path.is_file(), f"Run: (cd webapp && npm run screenshots) to generate {filename}"
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
