"""Source reviews must be explicit and remain separate from the canonical catalog."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from savoroute.api.app import create_app
from savoroute.cli import main
from savoroute.data.catalog import catalog_to_dict, load_catalog
from savoroute.evidence.review import (
    EvidenceError,
    catalog_digest,
    load_evidence_bundle,
    parse_proposals,
    prepare_review,
    publish_evidence,
)


def example(catalog=None):
    catalog = catalog or load_catalog()
    return {
        "schema_version": 1,
        "catalog_digest": catalog_digest(catalog),
        "claims": [
            {"claim_id": "menu1", "item_id": "r001", "kind": "menu_url",
             "value": "https://example.org/menu", "source_url": "https://example.org/menus",
             "observed_on": "2026-11-12", "license": None, "attribution": None},
            {"claim_id": "image1", "item_id": "r001", "kind": "image_url",
             "value": "https://commons.wikimedia.org/wiki/File:Food.jpg",
             "source_url": "https://commons.wikimedia.org/wiki/File:Food.jpg",
             "observed_on": "2026-11-12", "license": "CC-BY-4.0",
             "attribution": "Demo photographer"},
            {"claim_id": "cuisine1", "item_id": "r002", "kind": "cuisine",
             "value": "Mediterranean", "source_url": "https://example.org/restaurant",
             "observed_on": "2026-11-12", "license": None, "attribution": None},
        ],
    }


def write_json(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def reviewed(tmp_path, *, reject="cuisine1"):
    catalog = load_catalog()
    proposals, review, bundle = (tmp_path / p for p in ("proposals.json", "review.json", "bundle.json"))
    write_json(proposals, example())
    assert prepare_review(catalog, proposals, review) == 3
    data = json.loads(review.read_text())
    for row in data["decisions"]:
        row.update({"decision": "reject" if row["claim_id"] == reject else "approve",
                    "reviewer": "example-reviewer", "reason": "Evidence checked for demo",
                    "reviewed_on": "2026-11-12"})
    write_json(review, data)
    return catalog, proposals, review, bundle


def test_review_requires_exhaustive_explicit_decisions(tmp_path):
    catalog, proposals, review, bundle = reviewed(tmp_path)
    data = json.loads(review.read_text())
    data["decisions"][0]["decision"] = None
    write_json(review, data)
    with pytest.raises(EvidenceError, match="explicit"):
        publish_evidence(catalog, proposals, review, bundle)
    assert not bundle.exists()


def test_approved_evidence_bound_to_catalog_and_served_separately(tmp_path):
    catalog, proposals, review, bundle = reviewed(tmp_path)
    published = publish_evidence(catalog, proposals, review, bundle)
    assert len(published["claims"]) == 2
    assert not any(e["kind"] == "cuisine" for e in published["claims"])
    assert load_evidence_bundle(bundle, catalog) == published
    with TestClient(create_app(evidence_path=bundle)) as client:
        item = client.get("/v1/items/r001").json()
        assert "reviewed_claims" not in item
        result = client.get("/v1/items/r001/evidence")
        assert result.status_code == 200
        assert {e["kind"] for e in result.json()["reviewed_claims"]} == {"menu_url", "image_url"}
        assert result.json()["reviewed_claims"][1]["attribution"] == "Demo photographer"
        assert "reviewer" not in result.json()["reviewed_claims"][1]
        assert "reason" not in result.json()["reviewed_claims"][1]
        assert client.get("/v1/items/r002/evidence").json()["reviewed_claims"] == []
        assert client.get("/v1/items/no-such-record/evidence").status_code == 404
    # None of the new source material changes canonical retrieval data.
    assert catalog_to_dict(catalog) == catalog_to_dict(load_catalog())


def test_mismatch_rejects_stale_bundle(tmp_path):
    catalog, proposals, review, bundle = reviewed(tmp_path)
    publish_evidence(catalog, proposals, review, bundle)
    changed = catalog_to_dict(catalog)
    changed["items"][0]["description"] = "Changed source record"
    from savoroute.data.catalog import parse_catalog
    with pytest.raises(EvidenceError, match="different catalog"):
        load_evidence_bundle(bundle, parse_catalog(changed))
    with pytest.raises(EvidenceError, match="different catalog"):
        create_app(catalog_path=_catalog_file(tmp_path, changed), evidence_path=bundle)


def _catalog_file(tmp_path, content):
    file = tmp_path / "catalog.json"
    write_json(file, content)
    return file


@pytest.mark.parametrize("mutation,pattern", [
    (lambda d: d["claims"][0].update({"item_id": "absent"}), "unknown catalog item"),
    (lambda d: d["claims"][0].update({"kind": "hidden"}), "unrecognized evidence kind"),
    (lambda d: d["claims"][0].update({"value": "http://example.org/menu"}), "public HTTPS"),
    (lambda d: d["claims"][1].update({"license": None}), "open license"),
    (lambda d: d["claims"][1].update({"attribution": None}), "attribution"),
    (lambda d: d["claims"][0].update({"source_url": "javascript:alert(1)"}), "public HTTPS"),
    (lambda d: d["claims"][0].update({"source_url": "https://192.168.1.4/a"}), "private network"),
    (lambda d: d["claims"].append(deepcopy(d["claims"][0])), "unique"),
    (lambda d: d.update({"catalog_digest": "0" * 64}), "catalog digest"),
])
def test_rejects_invalid_manifest(mutation, pattern):
    data = example()
    mutation(data)
    with pytest.raises(EvidenceError, match=pattern):
        parse_proposals(data, load_catalog())


def test_conflicting_approved_menus_must_be_reviewed(tmp_path):
    catalog = load_catalog()
    data = example()
    additional = deepcopy(data["claims"][0])
    additional.update({"claim_id": "menu2", "value": "https://another.org/menu"})
    data["claims"].append(additional)
    proposal = tmp_path / "proposal.json"
    review = tmp_path / "review.json"
    out = tmp_path / "published.json"
    write_json(proposal, data)
    prepare_review(catalog, proposal, review)
    decisions = json.loads(review.read_text())
    for row in decisions["decisions"]:
        row.update({"decision": "approve", "reviewer": "reviewer", "reason": "demo",
                    "reviewed_on": "2026-11-12"})
    write_json(review, decisions)
    with pytest.raises(EvidenceError, match="multiple approved menus"):
        publish_evidence(catalog, proposal, review, out)


def test_review_is_bound_to_exact_proposal_file(tmp_path):
    catalog, proposals, review, bundle = reviewed(tmp_path)
    data = json.loads(proposals.read_text())
    data["claims"][0]["value"] = "https://changed.org/menu"
    write_json(proposals, data)
    with pytest.raises(EvidenceError, match="review does not match"):
        publish_evidence(catalog, proposals, review, bundle)
    assert not bundle.exists()


def test_no_overwrite_and_default_api_is_empty(tmp_path):
    catalog, proposals, review, bundle = reviewed(tmp_path)
    publish_evidence(catalog, proposals, review, bundle)
    with pytest.raises(FileExistsError):
        publish_evidence(catalog, proposals, review, bundle)
    with TestClient(create_app()) as client:
        result = client.get("/v1/items/r001/evidence")
        assert result.status_code == 200
        assert result.json()["reviewed_claims"] == []


def test_cli_round_trip(tmp_path: Path, capsys):
    catalog = _catalog_file(tmp_path, catalog_to_dict(load_catalog()))
    proposal = tmp_path / "proposal.json"
    review = tmp_path / "review.json"
    published = tmp_path / "published.json"
    write_json(proposal, example())
    assert main(["evidence", "prepare", "--catalog", str(catalog),
                 "--proposals", str(proposal), "--output", str(review)]) == 0
    raw = json.loads(review.read_text())
    for row in raw["decisions"]:
        row.update({"decision": "approve", "reviewer": "demo", "reason": "reviewed",
                    "reviewed_on": "2026-11-12"})
    write_json(review, raw)
    assert main(["evidence", "publish", "--catalog", str(catalog),
                 "--proposals", str(proposal), "--review", str(review),
                 "--output", str(published)]) == 0
    assert "Published 3" in capsys.readouterr().out


def test_review_date_is_not_before_observation(tmp_path):
    catalog, proposals, review, bundle = reviewed(tmp_path)
    sheet = json.loads(review.read_text())
    sheet["decisions"][0]["reviewed_on"] = "2026-11-11"
    write_json(review, sheet)
    with pytest.raises(EvidenceError, match="cannot precede"):
        publish_evidence(catalog, proposals, review, bundle)


def test_unapproved_claim_fails_closed_if_bundle_tampered(tmp_path):
    catalog, proposals, review, bundle = reviewed(tmp_path)
    publish_evidence(catalog, proposals, review, bundle)
    saved = json.loads(bundle.read_text())
    saved["claims"][0]["review"]["decision"] = "reject"
    write_json(bundle, saved)
    with pytest.raises(EvidenceError, match="approved review"):
        load_evidence_bundle(bundle, catalog)


def test_bundled_fictional_review_fixture_is_reproducible():
    fixture = Path(__file__).resolve().parents[1] / "data/sample/evidence_candidates_demo.json"
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    _, claims = parse_proposals(raw, load_catalog())
    assert [claim.claim_id for claim in claims] == ["sample_menu", "sample_cuisine"]
