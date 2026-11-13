import json
import subprocess
import sys
from pathlib import Path

import pytest

from savoroute.data.catalog import load_catalog
from savoroute.evidence.review import catalog_digest

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / 'data/generated/real-pilot/catalog.json'


def test_unresolved_export_is_audit_not_geocoding(tmp_path):
    if not PILOT.is_file():
        pytest.skip("optional, Git-ignored normalized Boston pilot is not present")
    if sum(item.city == "Boston" for item in load_catalog(PILOT).items) != 124:
        pytest.skip("Boston pilot is from a pre-normalization revision")
    out = tmp_path / 'unresolved.json'
    cmd = [sys.executable, 'scripts/export_unresolved_boston.py', '--catalog', str(PILOT), '--output', str(out)]
    result = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(out.read_text())
    assert payload['unresolved_restaurants'] == 41
    assert payload['catalog_digest'] == catalog_digest(load_catalog(PILOT))
    assert len({r['item_id'] for r in payload['records']}) == 41
    assert all(r['status'] == 'municipality_unresolved' and r['assignment'] is None
               and r['latitude'] is not None and r['longitude'] is not None
               for r in payload['records'])
    assert subprocess.run(cmd, cwd=ROOT, capture_output=True).returncode != 0
    assert PILOT.is_file()
