"""Human labels and real-world gates cannot be replaced by synthetic fixtures."""

from __future__ import annotations

from datetime import date

import pytest

from scripts.review_quality_gate import run_gate, validate_reviewed_dataset


def case(reviewed=True, success=True):
    return {"id": "a", "review_status": "reviewed" if reviewed else "unreviewed",
            "reviewed_by": "Researcher A", "reviewed_at": date.today().isoformat(),
            "reviewer_notes": "Reviewed independently against actual public source",
            "request": {"cuisine": "Persian", "city": "Boston", "region": "MA",
                        "country": "United States"}, "answerable": True,
            "relevant_ids": ["restaurant-a"],
            "results": ([{"id": "restaurant-a", "cuisine": "Persian", "city": "Boston",
                        "region": "MA", "country": "United States",
                        "source_url": "https://example.org/a"}] if success else [])}


def test_template_and_synthetic_not_accepted():
    for label in ("unreviewed_100_query_template", "synthetic_fixture"):
        with pytest.raises(ValueError):
            validate_reviewed_dataset({"dataset_type": label, "cases": [case()]}, minimum=1)


def test_unreviewed_data_fails_closed():
    with pytest.raises(ValueError, match="review_status"):
        validate_reviewed_dataset({"dataset_type": "real_reviewed", "cases": [case(False)]},
                                  minimum=1)


def test_valid_reviewed_sample_passes_configured_tiny_unit_threshold():
    report = run_gate({"dataset_type": "real_reviewed", "cases": [case()]}, minimum=1,
                      minimum_answerable=1, minimum_unanswerable=0,
                      success=0.8, abstention=0, source_coverage=1)
    assert report["passed"] is True
    assert report["success_at_5_answerable"] == 1


def test_relevant_case_without_answer_fails_release_gate():
    report = run_gate({"dataset_type": "real_reviewed", "cases": [case(success=False)]},
                      minimum=1, minimum_answerable=1, minimum_unanswerable=0,
                      success=0.8, abstention=0, source_coverage=0)
    assert report["passed"] is False


def test_preflight_does_not_print_secrets_or_claim_completed_deployment(tmp_path):
    from savoroute.live.review import LiveReviewRegistry
    from scripts.beta_preflight import preflight

    data = tmp_path / "private"
    data.mkdir(mode=0o700)
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{}", encoding="utf-8")
    frontend = tmp_path / "index.html"
    frontend.write_text("<html></html>", encoding="utf-8")
    reviews = tmp_path / "reviews.json"
    reviews.write_text('{"schema_version": 1, "records": []}', encoding="utf-8")
    assert not LiveReviewRegistry.load(reviews).reviews
    env = {"SAVOROUTE_BETA_ENABLED": "1", "SAVOROUTE_BETA_USAGE_DB": str(data / "db"),
           "SAVOROUTE_BETA_IDENTITY_SECRET": "VERY_PRIVATE_SECRET_VALUE" * 4,
           "SAVOROUTE_BETA_TRUSTED_HOSTS": "beta.example.com",
           "SAVOROUTE_LIVE_ENABLED": "1", "SAVOROUTE_LIVE_REVIEW_FILE": str(reviews),
           "SAVOROUTE_OPENAI_API_KEY": "sk-SHOULD_NOT_APPEAR"}
    result = preflight(env, catalog=catalog, frontend=frontend)
    assert result["configuration"] == "valid"
    assert result["tls_and_edge_auth_verified"] is False
    assert "sk-SHOULD_NOT_APPEAR" not in str(result)
    assert "VERY_PRIVATE_SECRET_VALUE" not in str(result)
    with pytest.raises(ValueError, match="human review"):
        preflight({k: v for k, v in env.items() if k != "SAVOROUTE_LIVE_REVIEW_FILE"},
                  catalog=catalog, frontend=frontend)


def test_captured_response_requires_human_labels():
    from scripts.prepare_review_case import prepare

    response = {"provider": "fixture", "requested_cuisine": "Persian",
                "requested_city": "Boston", "catalog_results": [],
                "web_results": [{"name": "Example Persian Restaurant", "city": "Boston",
                                 "region": "MA", "country": "United States",
                                 "cuisine": "Persian", "source_url": "https://example.org/a",
                                 "source_title": "Example"}]}
    request = {"cuisine": "Persian", "city": "Boston", "region": "MA",
               "country": "United States"}
    row = prepare("q001", request, response)
    assert row["review_status"] == "unreviewed"
    assert row["answerable"] is None
    assert row["results"][0]["id"].startswith("web-")
    with pytest.raises(ValueError, match="do not match"):
        prepare("q002", {**request, "city": "Cambridge"}, response)
