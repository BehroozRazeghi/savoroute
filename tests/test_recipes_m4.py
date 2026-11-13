"""Regression and adversarial checks for source-linked, unverified recipe imports."""
import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from savoroute.api.app import create_app
from savoroute.data.catalog import catalog_to_dict, load_catalog
from savoroute.ingestion.osm import import_osm_snapshot
from savoroute.quality.audit import audit_catalog
from savoroute.quality.osm_facts import build_osm_source_facts, read_osm_snapshot
from savoroute.quality.recipes import (
    RecipeCurationError,
    export_recipe_catalog,
    load_recipe_notes,
    prepare_recipe_catalog,
    read_recipe_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / 'data/generated/real-pilot'
MANIFEST = ROOT / 'data/curated/wikibooks-recipes-pilot-v1.json'


@pytest.fixture
def source():
    return read_recipe_manifest(MANIFEST)


@pytest.fixture
def base():
    """Use real pilot when installed; otherwise a committed fictional test fixture."""
    pilot = PILOT / 'catalog.json'
    if pilot.is_file():
        catalog = load_catalog(pilot)
        if sum(item.city == 'Boston' for item in catalog.items) == 124:
            return catalog
    # This fixture models an externally sourced catalog; its records are fictional.
    snapshot = json.loads((ROOT / 'data/sample/osm_overpass_fixture.json').read_text())
    snapshot.pop('savoroute_fixture')
    return import_osm_snapshot(snapshot).catalog


def test_source_linked_additive_without_rewriting_restaurants(base, source):
    merged, notes, report = prepare_recipe_catalog(base, source)
    assert len(merged.items) == len(base.items) + 3
    assert merged.items[:len(base.items)] == base.items
    assert merged.synthetic is False
    assert len(notes['records']) == 3
    assert report['photo_count_added'] == 0
    assert all(x.kind == 'recipe' and not x.dietary_tags for x in merged.items[len(base.items):])
    assert all(x.source_url.startswith('https://en.wikibooks.org/wiki/Cookbook:') for x in merged.items[len(base.items):])
    assert all(len(x.ingredients) >= 2 for x in merged.items[len(base.items):])
    assert [x['review_status'] for x in notes['records']] == ['source_transcribed_unverified'] * 3
    assert audit_catalog(merged)['by_kind']['recipe']['total'] == 3


def test_merging_is_deterministic_against_packaged_outputs(base, source):
    if not (PILOT / 'catalog-with-recipes-v1.json').is_file() or len(base.items) != 165:
        pytest.skip("optional, Git-ignored Boston pilot outputs are not present")
    merged, notes, report = prepare_recipe_catalog(base, source)
    assert merged == load_catalog(PILOT / 'catalog-with-recipes-v1.json')
    assert notes == json.loads((PILOT / 'recipe-notes-v1.json').read_text())
    assert report == json.loads((PILOT / 'recipe-build-report-v1.json').read_text())
    assert len(build_osm_source_facts(merged, read_osm_snapshot(PILOT / 'frozen/source.json'))['records']) == len(base.items)


@pytest.mark.parametrize('mutate', [
    lambda m: m['recipes'][0].update(source_license='All Rights Reserved'),
    lambda m: m['recipes'][0].update(source_url='http://localhost/wiki/Cookbook:Bad'),
    lambda m: m['recipes'][0].update(source_revision_url='https://evil.example/w/index.php?title=Cookbook:Hummus_III&oldid=2'),
    lambda m: m['recipes'][0].update(source_revision_url='https://en.wikibooks.org/w/index.php?title=Cookbook:Other&oldid=42'),
    lambda m: m['recipes'][0].update(source_checked_on='2099-01-01'),
    lambda m: m['recipes'][0].update(ingredients=['a single item']),
    lambda m: m['recipes'][0].update(steps=['<script>bad()</script>']),
    lambda m: m['recipes'].append(copy.deepcopy(m['recipes'][0])),
    lambda m: m['recipes'][0].update(dietary_tags=['vegan']),
])
def test_reject_invalid_or_unjustified_source(base, source, mutate):
    edited = copy.deepcopy(source)
    mutate(edited)
    if edited['recipes'][0]['steps'] == ['<script>bad()</script>']:
        # Single-line procedure rejected as incomplete even if HTML safely displayed.
        pass
    with pytest.raises(RecipeCurationError):
        prepare_recipe_catalog(base, edited)


def test_reject_fictional_catalog(base, source):
    with pytest.raises(RecipeCurationError):
        prepare_recipe_catalog(load_catalog(), source)


def test_reject_duplicate_catalog_recipe(base, source):
    merged, _, _ = prepare_recipe_catalog(base, source)
    with pytest.raises(RecipeCurationError):
        prepare_recipe_catalog(merged, source)


def test_nonoverwriting_export_and_source_collision(base, source, tmp_path):
    c, n, q = (tmp_path / s for s in ('catalog.json','notes.json','report.json'))
    export_recipe_catalog(base, source, catalog_path=c, notes_path=n, report_path=q,
                          manifest_path=MANIFEST)
    for path in (c, n, q):
        assert path.is_file()
    from savoroute.ingestion.sources import IngestionError
    with pytest.raises(IngestionError):
        export_recipe_catalog(base, source, catalog_path=c, notes_path=n, report_path=q,
                              manifest_path=MANIFEST)
    with pytest.raises(RecipeCurationError):
        export_recipe_catalog(base, source, catalog_path=MANIFEST, notes_path=n,
                              report_path=q, manifest_path=MANIFEST)
    assert read_recipe_manifest(MANIFEST) == source


def test_note_integrity_and_catalog_digest(base, source, tmp_path):
    merged, notes, _ = prepare_recipe_catalog(base, source)
    file = tmp_path / 'notes.json'
    file.write_text(json.dumps(notes))
    assert len(load_recipe_notes(file, merged)['records']) == 3
    with pytest.raises(RecipeCurationError, match='catalog digest'):
        load_recipe_notes(file, base)
    edits = copy.deepcopy(notes)
    edits['records'][0]['steps'] = ['changed']
    file.write_text(json.dumps(edits))
    with pytest.raises(RecipeCurationError):
        load_recipe_notes(file, merged)
    edits = copy.deepcopy(notes)
    edits['records'][0]['source_license_url'] = 'https://example.com/not-the-license'
    file.write_text(json.dumps(edits))
    with pytest.raises(RecipeCurationError):
        load_recipe_notes(file, merged)
    edits = copy.deepcopy(notes)
    edits['records'].append(copy.deepcopy(edits['records'][0]))
    file.write_text(json.dumps(edits))
    with pytest.raises(RecipeCurationError):
        load_recipe_notes(file, merged)


def test_http_recipe_notes_and_auth(tmp_path, base, source):
    catalog_file, notes_file, report_file = (tmp_path / n for n in ('catalog.json', 'notes.json', 'report.json'))
    export_recipe_catalog(base, source, catalog_path=catalog_file, notes_path=notes_file,
                          report_path=report_file)
    merged = load_catalog(catalog_file)
    recipe_id = next(x.item_id for x in merged.items if x.kind == 'recipe')
    with TestClient(create_app(catalog_path=catalog_file, recipe_notes_path=notes_file,
                               api_key='secret')) as client:
        assert client.get('/v1/meta').status_code == 401
        headers={'x-api-key':'secret'}
        meta = client.get('/v1/meta', headers=headers).json()
        assert meta['recipe_notes_records'] == 3 and meta['catalog_items'] == len(base.items) + 3
        assert client.get(f'/v1/items/{recipe_id}/recipe-notes').status_code == 401
        result = client.get(f'/v1/items/{recipe_id}/recipe-notes', headers=headers)
        assert result.status_code == 200
        assert result.json()['source_license'] == 'CC-BY-SA-4.0'
        assert result.json()['review_status'] == 'source_transcribed_unverified'
        assert len(result.json()['steps']) > 2
        restaurant_id = merged.items[0].item_id
        assert client.get(f'/v1/items/{restaurant_id}/recipe-notes', headers=headers).json()['steps'] == []
        assert client.get('/v1/items/no-such-item/recipe-notes', headers=headers).status_code == 404
        found = client.post('/v1/search', json={'query':'lentil', 'filters':{'kind':'recipe'}},headers=headers)
        assert found.status_code == 200
        assert any(x['item']['title']=='Red Lentil Soup' for x in found.json()['results'])
    with TestClient(create_app(catalog_path=catalog_file)) as client:
        assert client.get(f'/v1/items/{recipe_id}/recipe-notes').json()['review_status'] == 'not_configured'
    base_path = tmp_path / 'original-catalog.json'
    base_path.write_text(json.dumps(catalog_to_dict(base)))
    with pytest.raises(RecipeCurationError):
        create_app(catalog_path=base_path, recipe_notes_path=notes_file)
