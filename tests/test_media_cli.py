"""Media CLI output uses the same library functionality as notebooks."""

import json
from pathlib import Path

from savoroute.cli import main
from savoroute.data.catalog import load_catalog

SAMPLE = Path(__file__).resolve().parents[1] / "data/sample"


def test_media_ingest_cli(tmp_path, capsys):
    dest = tmp_path / "media-export"
    assert main(["media", "ingest", "--manifest", str(SAMPLE / "image_manifest.json"),
                 "--output-dir", str(dest)]) == 0
    assert "Imported 2 images" in capsys.readouterr().out
    assert len(load_catalog(dest / "catalog.json").media) == 2
    assert json.loads((dest / "provenance.json").read_text())["schema_version"] == 1


def test_media_cli_no_overwrite(tmp_path, capsys):
    dest = tmp_path / "media-export"
    args = ["media", "ingest", "--manifest", str(SAMPLE / "image_manifest.json"),
            "--output-dir", str(dest)]
    assert main(args) == 0
    capsys.readouterr()
    assert main(args) == 2
    assert "already exists" in capsys.readouterr().err
