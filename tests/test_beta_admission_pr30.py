"""Shared and fail-closed public-beta admission tests. No paid calls or network."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from savoroute.ai.contracts import FoodInterpretation
from savoroute.api.app import create_app
from savoroute.beta.admission import (
    AdmissionLimited,
    AdmissionUnavailable,
    BetaAdmission,
    BetaPolicy,
)
from savoroute.live.contracts import WebRestaurant


class FakeAI:
    name = "fixture"

    def __init__(self):
        self.calls = 0

    async def interpret(self, _prompt, _image):
        self.calls += 1
        return FoodInterpretation(
            search_query="Persian food", dishes=[], cuisines=["Persian"],
            ingredients=[], uncertainties=[],
        )


class FakeLive:
    name = "fixture"

    def __init__(self):
        self.calls = 0

    async def search(self, _payload):
        self.calls += 1
        return [WebRestaurant(
            name="Sample Iranian Restaurant", city="Boston", region="MA",
            country="United States", cuisine="Iranian",
            source_url="https://directory.example/sample", source_title="Fixture only",
        )]


def policy(tmp_path: Path, **overrides) -> BetaPolicy:
    values = {
        "database": tmp_path / "usage.sqlite3",
        "identity_secret": b"a-fresh-test-secret-at-least-32-bytes-long",
        "ai_attempts_per_utc_day": 3,
        "live_attempts_per_utc_day": 2,
        "client_attempts_per_minute": 2,
        "trusted_hosts": ("testserver", "localhost"),
    }
    values.update(overrides)
    return BetaPolicy(**values)


def live_request():
    return {"query": "kebab", "cuisine": "Persian", "city": "Boston",
            "region": "MA", "country": "United States",
            "consent_remote_processing": True}


def test_opt_in_configuration_is_explicit_and_rejects_unsafe_values(tmp_path):
    assert BetaPolicy.from_environ({}) is None
    env = {"SAVOROUTE_BETA_ENABLED": "1", "SAVOROUTE_BETA_USAGE_DB": str(tmp_path / "db"),
           "SAVOROUTE_BETA_IDENTITY_SECRET": "X" * 40,
           "SAVOROUTE_BETA_TRUSTED_HOSTS": "testserver,localhost",
           "SAVOROUTE_BETA_AI_DAILY": "4", "SAVOROUTE_BETA_LIVE_DAILY": "2"}
    result = BetaPolicy.from_environ(env)
    assert result is not None
    assert result.ai_attempts_per_utc_day == 4
    for key, value in (
        ("SAVOROUTE_BETA_USAGE_DB", "relative.sqlite"),
        ("SAVOROUTE_BETA_IDENTITY_SECRET", "too-short"),
        ("SAVOROUTE_BETA_TRUSTED_HOSTS", "*"),
        ("SAVOROUTE_BETA_AI_DAILY", "0"),
        ("SAVOROUTE_BETA_AI_DAILY", "NaN"),
        ("SAVOROUTE_BETA_CLIENT_MINUTE", "1000"),
        ("SAVOROUTE_BETA_ENABLED", "true"),
    ):
        with pytest.raises(ValueError):
            BetaPolicy.from_environ({**env, key: value})


def test_cross_instance_atomic_budget_and_per_client_limit(tmp_path):
    settings = policy(tmp_path)
    first = BetaAdmission(settings)
    second = BetaAdmission(settings)
    epoch = 60 * 9000
    first.admit("live", "10.0.0.1", now=epoch)
    second.admit("live", "10.0.0.2", now=epoch)
    with pytest.raises(AdmissionLimited, match="Daily beta"):
        first.admit("live", "10.0.0.3", now=epoch)
    first.admit("ai", "10.0.0.1", now=epoch)
    second.admit("ai", "10.0.0.1", now=epoch)
    with pytest.raises(AdmissionLimited, match="Too many requests"):
        second.admit("ai", "10.0.0.1", now=epoch)
    first.admit("ai", "10.0.0.2", now=epoch)
    with pytest.raises(AdmissionLimited, match="Daily beta"):
        second.admit("ai", "10.0.0.3", now=epoch + 60)
    assert first.totals(day="1970-01-07") == {"ai": 3, "live": 2}
    assert first.totals(day="1970-01-08") == {}
    with sqlite3.connect(settings.database) as db:
        fields = db.execute("SELECT client_fingerprint FROM minute_attempts").fetchall()
        assert fields and all(len(row[0]) == 64 for row in fields)
        assert "10.0.0.1" not in str(fields)
        count = db.execute("SELECT SUM(attempts) FROM daily_attempts").fetchone()[0]
        assert count == 5


def test_missing_or_corrupted_database_fails_closed(tmp_path):
    settings = policy(tmp_path)
    manager = BetaAdmission(settings)
    settings.database.unlink()
    assert manager.ready() is False
    with pytest.raises(AdmissionUnavailable):
        manager.admit("live", "person", now=1000)
    assert not settings.database.exists()
    settings.database.write_bytes(b"not-sqlite")
    with pytest.raises(AdmissionUnavailable):
        manager.admit("live", "person", now=1001)


def test_file_is_private_and_symlink_is_rejected(tmp_path):
    settings = policy(tmp_path)
    BetaAdmission(settings)
    assert settings.database.stat().st_mode & 0o077 == 0
    settings.database.unlink()
    settings.database.symlink_to(tmp_path / "other")
    with pytest.raises(ValueError, match="symlink"):
        BetaAdmission(settings)


def test_paid_routes_enforce_shared_limits_without_affecting_public_catalog(tmp_path):
    settings = policy(tmp_path, ai_attempts_per_utc_day=1, live_attempts_per_utc_day=1)
    admissions = BetaAdmission(settings)
    ai = FakeAI()
    live = FakeLive()
    with TestClient(create_app(
        ai_provider=ai, live_provider=live, beta_admission=admissions,
    )) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").json()["status"] == "ready"
        assert client.get("/v1/items").status_code == 200
        headers = client.get("/v1/items").headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"
        assert client.post("/v1/ai/interpret", json={
            "prompt": "Persian dishes", "consent_remote_processing": True,
        }).status_code == 200
        ai_limited = client.post("/v1/ai/interpret", json={
            "prompt": "Persian dishes", "consent_remote_processing": True,
        })
        assert ai_limited.status_code == 429
        assert ai_limited.headers["retry-after"].isdigit()
        assert ai_limited.headers["cache-control"] == "no-store"
        assert client.post("/v1/live/discover", json=live_request()).status_code == 200
        assert client.post("/v1/live/discover", json=live_request()).status_code == 429
        assert (ai.calls, live.calls) == (1, 1)
        assert client.get("/v1/items").status_code == 200


def test_host_filter_and_missing_budget_database_deny_paid_calls(tmp_path):
    settings = policy(tmp_path)
    manager = BetaAdmission(settings)
    ai = FakeAI()
    with TestClient(create_app(ai_provider=ai, beta_admission=manager)) as client:
        assert client.get("/v1/items", headers={"host": "evil.example"}).status_code == 400
        settings.database.unlink()
        assert client.get("/readyz").status_code == 503
        response = client.post("/v1/ai/interpret", json={
            "prompt": "Persian food", "consent_remote_processing": True,
        })
        assert response.status_code == 503
        assert ai.calls == 0
        assert "secret" not in response.text.lower()


def test_invalid_consent_and_body_do_not_consume_budget(tmp_path):
    manager = BetaAdmission(policy(tmp_path, ai_attempts_per_utc_day=1))
    ai = FakeAI()
    with TestClient(create_app(ai_provider=ai, beta_admission=manager)) as client:
        assert client.post("/v1/ai/interpret", json={"prompt": "x"}).status_code == 422
        assert client.post("/v1/ai/interpret", json={
            "prompt": "Persian food", "consent_remote_processing": True,
        }).status_code == 200
        assert ai.calls == 1
        assert manager.totals().get("ai") == 1


def test_server_rejects_incomplete_beta_configuration_before_listening(monkeypatch):
    from savoroute.api.server import serve

    called = []
    monkeypatch.setenv("SAVOROUTE_BETA_ENABLED", "1")
    monkeypatch.delenv("SAVOROUTE_BETA_USAGE_DB", raising=False)
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: called.append(args))
    with pytest.raises(ValueError, match="SAVOROUTE_BETA_USAGE_DB"):
        serve()
    assert not called


def test_simultaneous_admissions_cannot_exceed_global_cap(tmp_path):
    settings = policy(tmp_path, ai_attempts_per_utc_day=5,
                      client_attempts_per_minute=30)
    managers = [BetaAdmission(settings) for _ in range(4)]

    def attempt(n):
        try:
            managers[n % 4].admit("ai", f"client-{n}", now=720000)
            return True
        except AdmissionLimited:
            return False

    with ThreadPoolExecutor(max_workers=12) as pool:
        admitted = list(pool.map(attempt, range(30)))
    assert sum(admitted) == 5
    assert managers[0].totals(day="1970-01-09") == {"ai": 5}


def test_usage_cli_shows_only_aggregate_attempts(tmp_path, capsys, monkeypatch):
    from scripts.beta_usage import main

    settings = policy(tmp_path)
    manager = BetaAdmission(settings)
    manager.admit("ai", "someone-private", now=720000)
    monkeypatch.setattr("sys.argv", ["beta_usage", str(settings.database),
                                       "--day", "1970-01-09"])
    main()
    printed = capsys.readouterr().out
    assert "ai: 1" in printed and "live: 0" in printed
    assert "someone-private" not in printed


def test_server_rejects_nonloopback_even_with_beta_configured(tmp_path, monkeypatch):
    from savoroute.api.server import serve

    monkeypatch.setenv("SAVOROUTE_BETA_ENABLED", "1")
    monkeypatch.setenv("SAVOROUTE_BETA_USAGE_DB", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setenv("SAVOROUTE_BETA_IDENTITY_SECRET", "s" * 40)
    monkeypatch.setenv("SAVOROUTE_BETA_TRUSTED_HOSTS", "testserver")
    monkeypatch.setenv("SAVOROUTE_API_KEY", "test-api-secret")
    called = []
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: called.append(args))
    with pytest.raises(ValueError, match="loopback"):
        serve(host="0.0.0.0")
    assert not called
