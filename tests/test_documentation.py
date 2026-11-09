"""Check that relative links in maintained Markdown files resolve."""

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def test_local_markdown_links_exist() -> None:
    paths = [ROOT / "README.md", ROOT / "CONTRIBUTING.md"]
    for section in ("data", "docs", "notebooks", "scripts"):
        paths.extend((ROOT / section).rglob("*.md"))
    missing: list[str] = []
    for document in paths:
        for match in LINK.finditer(document.read_text(encoding="utf-8")):
            target = match.group(1).split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = document.parent / unquote(target)
            if not resolved.exists():
                missing.append(f"{document.relative_to(ROOT)}: {target}")
    assert missing == []
