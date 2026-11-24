"""Controlled-beta review gates use only manually approved exact-source claims."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from savoroute.api.app import create_app
from savoroute.beta.admission import BetaAdmission, BetaPolicy
from savoroute.live.contracts import WebRestaurant
from savoroute.live.review import LiveReviewRegistry


class FakeLive:
    name = "fixture"

    async def search(self, _request):
        return [
            WebRestaurant(name="Sample Persian Bistro", city="Boston", region="MA",
                          country="United States", cuisine="Persian",
                          source_url="https://example.org/persian", source_title="Source"),
            WebRestaurant(name="Mediterranean Grill", city="Cambridge", region="MA",
                          country="United States", cuisine="Persian",
                          source_url="https://example.org/grill", source_title="Source"),
        ]


def record(name="Sample Persian Bistro", decision="approved", days_ago=0,
           cuisine="Iranian", source_url="https://example.org/persian"):
    return {
        "name": name, "city": "Boston" if name.startswith("Sample") else "Cambridge",
        "region": "MA", "country": "United States", "cuisine": cuisine,
        "source_url": source_url, "decision": decision,
        "reviewer": "Reviewer-01" if decision != "pending" else "",
        "reviewed_on": ((date.today() - timedelta(days=days_ago)).isoformat()
                        if decision != "pending" else ""),
        "evidence_url": "https://example.org/persian-evidence" if decision == "approved" else "",
        "evidence_note": ("Human checked primary website against the requested cuisine and city"
                          if decision == "approved" else ""),
    }


def registry(tmp_path: Path, records: list[dict]) -> LiveReviewRegistry:
    path = tmp_path / "reviews.json"
    path.write_text(json.dumps({"schema_version": 1, "records": records}), encoding="utf-8")
    return LiveReviewRegistry.load(path)


def test_pending_missing_rejected_and_expired_leads_never_pass(tmp_path):
    lead = (pytest.importorskip("savoroute.live.contracts").WebRestaurant(
        name="Sample Persian Bistro", city="Boston", region="MA", country="United States",
        cuisine="Persian", source_url="https://example.org/persian", source_title="Source"))
    assert registry(tmp_path, []).filter([lead]) == []
    for state in ("pending", "rejected"):
        assert registry(tmp_path, [record(decision=state)]).filter([lead]) == []
    assert registry(tmp_path, [record(days_ago=91)]).filter([lead]) == []
    assert registry(tmp_path, [record(days_ago=89)]).filter([lead]) == [lead]


def test_approval_cannot_transfer_to_other_source_or_identity(tmp_path):
    reviewed = registry(tmp_path, [record()])
    candidate = WebRestaurant(name="Sample Persian Bistro", city="Boston", region="MA",
        country="United States", cuisine="Iranian", source_url="https://example.org/other",
        source_title="Source")
    assert reviewed.filter([candidate]) == []
    assert reviewed.filter([candidate.model_copy(update={"source_url": "https://example.org/persian",
                                                   "city": "Cambridge"})]) == []
    assert reviewed.filter([candidate.model_copy(update={"source_url": "https://example.org/persian"})])


def test_invalid_registry_rejected_at_startup(tmp_path):
    with pytest.raises(ValueError, match="evidence URL"):
        registry(tmp_path, [{**record(), "evidence_url": ""}])
    with pytest.raises(ValueError, match="duplicate"):
        registry(tmp_path, [record(), record()])
    with pytest.raises(ValueError, match="future"):
        registry(tmp_path, [{**record(), "reviewed_on":
                             (date.today() + timedelta(days=1)).isoformat()}])
    with pytest.raises(ValueError, match="public HTTPS"):
        registry(tmp_path, [{**record(), "source_url": "http://localhost/private"}])


def test_beta_api_shows_reviewed_only_not_broad_mediterranean(tmp_path):
    policy = BetaPolicy(database=tmp_path / "usage.sqlite3", identity_secret=b"x" * 40,
                        ai_attempts_per_utc_day=10, live_attempts_per_utc_day=10,
                        client_attempts_per_minute=10, trusted_hosts=("testserver",))
    approved = registry(tmp_path, [record()])
    app = create_app(live_provider=FakeLive(), live_review_registry=approved,
                     beta_admission=BetaAdmission(policy))
    with TestClient(app) as client:
        result = client.post("/v1/live/discover", json={
            "cuisine": "Persian", "city": "Boston", "region": "MA",
            "country": "United States", "geography_scope": "nearby",
            "nearby_cities": ["Cambridge"], "consent_remote_processing": True,
        })
        assert result.status_code == 200, result.text
        data = result.json()
        assert data["human_review_required"] is True
        assert [row["name"] for row in data["web_results"]] == ["Sample Persian Bistro"]
        assert client.get("/v1/live/status").json()["human_review_required"] is True


def test_beta_structured_logging_never_includes_query_or_secret(tmp_path, caplog):
    policy = BetaPolicy(database=tmp_path / "usage.sqlite3", identity_secret=b"x" * 40,
                        ai_attempts_per_utc_day=10, live_attempts_per_utc_day=10,
                        client_attempts_per_minute=10, trusted_hosts=("testserver",))
    app = create_app(beta_admission=BetaAdmission(policy))
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        with TestClient(app) as client:
            response = client.get("/readyz?private_prompt=SECRET_REVIEW_TEXT",
                                  headers={"Authorization": "Bearer PRIVATE_ACCESS_KEY"})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")
    events = [line for line in caplog.messages if '"event":"beta_http"' in line]
    assert len(events) == 1
    assert json.loads(events[0])["category"] == "readiness"
    assert "SECRET_REVIEW_TEXT" not in events[0]
    assert "PRIVATE_ACCESS_KEY" not in events[0]
    assert "private_prompt" not in events[0]


def test_beta_server_refuses_unreviewed_live_provider(monkeypatch, tmp_path):
    from savoroute.api.server import serve

    monkeypatch.setenv("SAVOROUTE_BETA_ENABLED", "1")
    monkeypatch.setenv("SAVOROUTE_BETA_USAGE_DB", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setenv("SAVOROUTE_BETA_IDENTITY_SECRET", "a" * 40)
    monkeypatch.setenv("SAVOROUTE_BETA_TRUSTED_HOSTS", "localhost,127.0.0.1")
    monkeypatch.setenv("SAVOROUTE_LIVE_ENABLED", "1")
    monkeypatch.setenv("SAVOROUTE_OPENAI_API_KEY", "fixture-not-real")
    monkeypatch.delenv("SAVOROUTE_LIVE_REVIEW_FILE", raising=False)
    with pytest.raises(ValueError, match="human reviews"):
        serve(host="127.0.0.1", port=8000)


def test_beta_server_disables_uvicorn_url_access_logs(monkeypatch, tmp_path):
    from savoroute.api.server import serve

    options = {}
    monkeypatch.setenv("SAVOROUTE_BETA_ENABLED", "1")
    monkeypatch.setenv("SAVOROUTE_BETA_USAGE_DB", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setenv("SAVOROUTE_BETA_IDENTITY_SECRET", "a" * 40)
    monkeypatch.setenv("SAVOROUTE_BETA_TRUSTED_HOSTS", "localhost,127.0.0.1")
    monkeypatch.setenv("SAVOROUTE_LIVE_ENABLED", "0")
    monkeypatch.setenv("SAVOROUTE_AI_ENABLED", "0")
    monkeypatch.setattr("uvicorn.run", lambda _app, **kwargs: options.update(kwargs))
    serve(host="127.0.0.1", port=8000)
    assert options["access_log"] is False
    assert options["proxy_headers"] is False
