"""Ingestion data contract, extraction evidence, and catalog admission."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from savoroute.cli import main
from savoroute.data.catalog import catalog_to_dict, load_catalog, parse_catalog
from savoroute.ingestion.extraction import (
    LabeledTextExtractor,
    ModelTextExtractor,
    parse_extraction,
)
from savoroute.ingestion.sources import IngestionError, parse_source_batch
from savoroute.providers.text import OllamaTextGenerator, OpenAITextGenerator
from savoroute.services.ingestion import ingest_sources, write_ingestion

FIXTURE = Path(__file__).parents[1] / "data/sample/ingestion_sources.json"


@pytest.fixture
def sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_demo_sources_and_spans(sample):
    batch = parse_source_batch(sample)
    result = ingest_sources(batch, LabeledTextExtractor(), base_catalog=load_catalog())
    assert len(result.catalog.items) == 14
    assert len(result.records) == 2
    assert result.catalog.synthetic
    assert result.records[0].item.title == "Ginger Mushroom Rice"
    evidence = result.records[0].evidence["ingredients"]
    assert len(evidence) == 4
    for field in result.records[0].evidence.values():
        for item in field:
            assert result.records[0].source.text[item.start:item.end] == item.quote
    assert result.records[0].source.sha256 == result.provenance()["records"][0]["source_sha256"]
    assert result.provenance()["provenance_schema_version"] == 1
    assert result.provenance()["source_dataset"] == "fictional-menu-excerpts"


def test_deterministic_ids_and_roundtrip(sample):
    batch = parse_source_batch(sample)
    records = ingest_sources(batch, LabeledTextExtractor(), base_catalog=load_catalog())
    reverse = parse_source_batch({**sample, "documents": list(reversed(sample["documents"]))})
    reversed_records = ingest_sources(reverse, LabeledTextExtractor(), base_catalog=load_catalog())
    assert {r.item.item_id for r in records.records} == {r.item.item_id for r in reversed_records.records}
    assert parse_catalog(catalog_to_dict(records.catalog)) == records.catalog


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(source_schema_version=True),
    lambda p: p["dataset"].update(synthetic="yes"),
    lambda p: p["dataset"].update(unknown=1),
    lambda p: p.update(documents=[]),
    lambda p: p["documents"][0].update(source_id=""),
    lambda p: p["documents"][0].update(source_url="file:///tmp/example"),
    lambda p: p["documents"][0].update(source_url="https://user:pass@example.org"),
    lambda p: p["documents"][0].update(collected_at="2026-11-09T12:00:00"),
    lambda p: p["documents"][0].update(kind="hotel"),
    lambda p: p["documents"][0].update(text="\x00"),
    lambda p: p["documents"][0].update(text="x" * 16001),
    lambda p: p["documents"].append(copy.deepcopy(p["documents"][0])),
    lambda p: p["documents"][0].update(unexpected="value"),
])
def test_invalid_source_batch(sample, mutation):
    mutation(sample)
    with pytest.raises(IngestionError):
        parse_source_batch(sample)


def test_normalization_and_source_hash(sample):
    sample["documents"][0]["text"] = "  Title: Café\r\nDescription: Café.  "
    source = parse_source_batch(sample).documents[0]
    assert source.text == "Title: Café\nDescription: Café."
    assert len(source.sha256) == 64


def test_missing_description_is_rejected(sample):
    sample["documents"][0]["text"] = "Title: Rice\nIngredients: rice"
    with pytest.raises(IngestionError, match="description"):
        ingest_sources(parse_source_batch(sample), LabeledTextExtractor(), base_catalog=load_catalog())


def test_duplicate_template_label_rejected(sample):
    sample["documents"][0]["text"] += "\nTitle: Another"
    with pytest.raises(IngestionError, match="duplicate field"):
        LabeledTextExtractor().extract(parse_source_batch(sample).documents[0])


def test_unknown_template_label_rejected(sample):
    sample["documents"][0]["text"] += "\nUnknown: anything"
    with pytest.raises(IngestionError, match="unsupported"):
        LabeledTextExtractor().extract(parse_source_batch(sample).documents[0])


def model_payload(source):
    return {
        "title": {"value": "Ginger Mushroom Rice", "quote": "Title: Ginger Mushroom Rice"},
        "description": {"value": "Rice with ginger, mushrooms, and scallions.",
                        "quote": "Description: Rice with ginger, mushrooms, and scallions."},
        "cuisines": [], "dietary_tags": [], "ingredients": [],
        "location": None, "price_tier": None,
    }


def test_model_output_contract(sample):
    source = parse_source_batch(sample).documents[0]

    class FakeGenerator:
        model_id = "stub"
        def generate(self, *, system_prompt, user_prompt):
            assert "untrusted data" in system_prompt
            assert source.text in user_prompt
            return json.dumps(model_payload(source))

    record = ModelTextExtractor(FakeGenerator()).extract(source)
    assert record.extractor_id == "model:stub"
    assert record.item.title == "Ginger Mushroom Rice"


def test_no_unsupported_model_claim(sample):
    source = parse_source_batch(sample).documents[0]
    payload = model_payload(source)
    payload["dietary_tags"] = [{"value": "gluten-free", "quote": "Dietary tags: vegetarian"}]
    with pytest.raises(IngestionError, match="not contained"):
        parse_extraction(payload, source, extractor_id="test")


def test_hallucinated_evidence_rejected(sample):
    source = parse_source_batch(sample).documents[0]
    payload = model_payload(source)
    payload["title"]["quote"] = "Title: A nonexistent recipe"
    with pytest.raises(IngestionError, match="not present verbatim"):
        parse_extraction(payload, source, extractor_id="test")


def test_extra_field_rejected(sample):
    source = parse_source_batch(sample).documents[0]
    payload = model_payload(source)
    payload["not_a_field"] = "unexpected"
    with pytest.raises(IngestionError, match="exactly"):
        parse_extraction(payload, source, extractor_id="test")


def test_recipe_location_rejected(sample):
    source = parse_source_batch(sample).documents[0]
    payload = model_payload(source)
    payload["location"] = {"value": "Rice", "quote": "Rice with ginger"}
    with pytest.raises(IngestionError, match="recipe cannot"):
        parse_extraction(payload, source, extractor_id="test")


def test_restaurant_requires_location(sample):
    source = parse_source_batch(sample).documents[1]
    payload = model_payload(source)
    payload["title"] = {"value": "Linden Kitchen", "quote": "Title: Linden Kitchen"}
    payload["description"] = {
        "value": "A fictional neighborhood restaurant serving seasonal vegetable dishes.",
        "quote": "Description: A fictional neighborhood restaurant serving seasonal vegetable dishes.",
    }
    with pytest.raises(IngestionError, match="requires source-supported location"):
        parse_extraction(payload, source, extractor_id="test")


def test_incorrect_price_tier_quote(sample):
    source = parse_source_batch(sample).documents[1]
    payload = {
        "title": {"value": "Linden Kitchen", "quote": "Title: Linden Kitchen"},
        "description": {
            "value": "A fictional neighborhood restaurant serving seasonal vegetable dishes.",
            "quote": "Description: A fictional neighborhood restaurant serving seasonal vegetable dishes."},
        "cuisines": [], "dietary_tags": [], "ingredients": [],
        "location": {"value": "Imaginary City", "quote": "Location: Imaginary City"},
        "price_tier": {"value": 3, "quote": "Price tier: 2"},
    }
    with pytest.raises(IngestionError, match="not supported"):
        parse_extraction(payload, source, extractor_id="test")


def test_model_errors_fail_closed(sample):
    source = parse_source_batch(sample).documents[0]

    class Broken:
        model_id = "stub"
        def generate(self, *, system_prompt, user_prompt):
            raise RuntimeError("private exception detail")

    with pytest.raises(IngestionError, match="text generation failed") as info:
        ModelTextExtractor(Broken()).extract(source)
    assert "private exception detail" not in str(info.value)


def test_invalid_model_json_rejected(sample):
    source = parse_source_batch(sample).documents[0]

    class Broken:
        model_id = "stub"
        def generate(self, *, system_prompt, user_prompt):
            return "```json\n{}\n```"

    with pytest.raises(IngestionError, match="not a JSON"):
        ModelTextExtractor(Broken()).extract(source)


def test_mixing_synthetic_and_real_rejected(sample):
    sample["dataset"]["synthetic"] = False
    with pytest.raises(IngestionError, match="synthetic"):
        ingest_sources(parse_source_batch(sample), LabeledTextExtractor(), base_catalog=load_catalog())


def test_duplicate_canonical_id_rejected(sample):
    batch = parse_source_batch(sample)
    first = ingest_sources(batch, LabeledTextExtractor(), base_catalog=load_catalog())
    with pytest.raises(IngestionError, match="already contains"):
        ingest_sources(batch, LabeledTextExtractor(), base_catalog=first.catalog)


def test_write_outputs_and_no_overwrite(tmp_path, sample):
    result = ingest_sources(parse_source_batch(sample), LabeledTextExtractor(), base_catalog=load_catalog())
    catalog = tmp_path / "output" / "catalog.json"
    report = tmp_path / "output" / "evidence.json"
    write_ingestion(result, catalog_path=catalog, provenance_path=report)
    assert parse_catalog(json.loads(catalog.read_text())) == result.catalog
    assert json.loads(report.read_text()) == result.provenance()
    assert result.provenance()["catalog_sha256"] == hashlib.sha256(catalog.read_bytes()).hexdigest()
    with pytest.raises(IngestionError, match="already exists"):
        write_ingestion(result, catalog_path=catalog, provenance_path=report)
    write_ingestion(result, catalog_path=catalog, provenance_path=report, overwrite=True)
    with pytest.raises(IngestionError, match="distinct"):
        write_ingestion(result, catalog_path=catalog, provenance_path=catalog, overwrite=True)


def test_failed_extraction_writes_nothing(tmp_path, sample):
    sample["documents"][1]["text"] = "Title: Missing description"
    with pytest.raises(IngestionError):
        result = ingest_sources(parse_source_batch(sample), LabeledTextExtractor(),
                                base_catalog=load_catalog())
        write_ingestion(result, catalog_path=tmp_path / "catalog.json",
                        provenance_path=tmp_path / "evidence.json")
    assert not list(tmp_path.iterdir())


def test_cli_ingest_and_search(tmp_path, capsys):
    catalog = tmp_path / "catalog.json"
    report = tmp_path / "evidence.json"
    args = ["ingest", "--sources", str(FIXTURE), "--output", str(catalog),
            "--provenance", str(report)]
    assert main(args) == 0
    assert "Ingested 2 sources" in capsys.readouterr().out
    assert main(["validate", "--catalog", str(catalog)]) == 0
    assert "items=14" in capsys.readouterr().out
    assert main(["search", "mushrooms", "--catalog", str(catalog), "--json"]) == 0
    hits = json.loads(capsys.readouterr().out)
    assert hits[0]["title"] == "Ginger Mushroom Rice"
    assert main(args) == 2
    assert "already exists" in capsys.readouterr().err


def test_cli_new_catalog(tmp_path, capsys):
    catalog = tmp_path / "new_catalog.json"
    report = tmp_path / "report.json"
    assert main(["ingest", "--sources", str(FIXTURE), "--new-catalog",
                 "--output", str(catalog), "--provenance", str(report)]) == 0
    assert len(json.loads(catalog.read_text())["items"]) == 2


def test_cli_provider_requires_model(tmp_path, capsys):
    assert main(["ingest", "--sources", str(FIXTURE), "--provider", "openai",
                 "--output", str(tmp_path / "catalog.json"),
                 "--provenance", str(tmp_path / "report.json")]) == 2
    assert "--model is required" in capsys.readouterr().err


def test_openai_adapter_with_injected_client():
    class Responses:
        def create(self, **kwargs):
            assert kwargs["model"] == "test-model"
            assert kwargs["instructions"] == "instructions"
            return SimpleNamespace(output_text='{"ok": true}')
    client = SimpleNamespace(responses=Responses())
    adapter = OpenAITextGenerator("test-model", client=client)
    assert adapter.generate(system_prompt="instructions", user_prompt="text") == '{"ok": true}'


def test_ollama_adapter_request(monkeypatch):
    from savoroute.providers import text as module

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def read(self, n):
            return json.dumps({"response": '{"ok": true}'}).encode()

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://127.0.0.1:11434/api/generate"
        body = json.loads(request.data)
        assert body["format"] == "json" and body["stream"] is False
        assert body["system"] == "instructions"
        return FakeResponse()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    adapter = OllamaTextGenerator("test-model")
    assert adapter.generate(system_prompt="instructions", user_prompt="text") == '{"ok": true}'


def test_ollama_bad_origin():
    with pytest.raises(ValueError, match="origin"):
        OllamaTextGenerator("test", base_url="file:///etc/passwd")
