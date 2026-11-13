"""Prevent regressions in the public repository's basic release claims."""

import re
from pathlib import Path

from savoroute import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_no_empty_root_notebook() -> None:
    assert not list(ROOT.glob("Untitled*.ipynb"))


def test_versions_agree() -> None:
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(r'^version = "' + re.escape(__version__) + r'"$', metadata, re.M)
    assert f"(`{__version__}`)" in readme


def test_notebook_index_is_complete() -> None:
    index = (ROOT / "notebooks" / "README.md").read_text(encoding="utf-8")
    notebooks = sorted((ROOT / "notebooks").glob("[0-9][0-9]_*.ipynb"))
    assert len(notebooks) == 21
    for path in notebooks:
        assert re.search(rf"\| {path.name[:2]} \|", index)


def test_pilot_data_not_implied_as_git_tracked() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "data/generated/" in ignore
    assert "not included in Git-tracked source" in readme
