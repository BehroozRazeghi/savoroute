"""Opt-in food AI: bounded input, consent, no secret/PII leaks or invented catalog claims."""

from __future__ import annotations

import asyncio
import base64
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from savoroute.ai.contracts import FoodInterpretation
from savoroute.ai.images import InvalidFoodImage, normalize_image
from savoroute.ai.provider import OpenAIResponsesProvider, ProviderUnavailable
from savoroute.api.app import create_app


class FakeFoodProvider:
    name = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, bytes | None]] = []

    async def interpret(self, prompt: str, image_jpeg: bytes | None) -> FoodInterpretation:
        self.calls.append((prompt, image_jpeg))
        if self.fail:
            raise ProviderUnavailable("Confidential upstream provider failure")
        return FoodInterpretation(
            search_query="tofu noodles", dishes=["tofu noodles"], cuisines=["Japanese"],
            ingredients=["tofu"], uncertainties=["Ingredients not confirmed"],
        )


def _image_bytes(format: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 150, 70)).save(buffer, format=format)
    return buffer.getvalue()


def _request(**kwargs):
    return {"prompt": "tofu noodles", "consent_remote_processing": True, **kwargs}


def test_ai_off_by_default_and_existing_catalog_unchanged():
    with TestClient(create_app()) as client:
        status = client.get("/v1/ai/status")
        assert status.status_code == 200
        assert status.json()["enabled"] is False
        assert status.json()["input_types"] == []
        no_ai = client.post("/v1/ai/interpret", json=_request())
        assert no_ai.status_code == 503
        assert no_ai.headers["cache-control"] == "no-store"
        assert client.get("/v1/items").status_code == 200
        assert client.post("/v1/search", json={"query": "tofu"}).status_code == 200


def test_consent_required_and_no_raw_prompt_reflected():
    provider = FakeFoodProvider()
    with TestClient(create_app(ai_provider=provider)) as client:
        assert client.get("/v1/ai/status").json()["enabled"] is True
        for content in (
            {"prompt": "my private text"},
            {"prompt": "my private text", "consent_remote_processing": False},
            {"prompt": "", "consent_remote_processing": True},
            {"prompt": "ok", "consent_remote_processing": True, "unrecognized": "secret"},
        ):
            response = client.post("/v1/ai/interpret", json=content)
            assert response.status_code == 422
            assert "private text" not in response.text
            assert "secret" not in response.text
        assert provider.calls == []


def test_real_image_validation_and_exif_free_jpeg_transmission():
    encoded = base64.b64encode(_image_bytes()).decode("ascii")
    provider = FakeFoodProvider()
    with TestClient(create_app(ai_provider=provider)) as client:
        response = client.post("/v1/ai/interpret", json=_request(image_base64=encoded))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        output = response.json()
        assert output["catalog_verified"] is False
        assert output["interpretation"]["search_query"] == "tofu noodles"
        assert "menu" in output["limitations"].lower()
        assert provider.calls[0][0] == "tofu noodles"
        normalized = provider.calls[0][1]
        assert normalized is not None
        assert normalized.startswith(b"\xff\xd8")
        with Image.open(io.BytesIO(normalized)) as image:
            assert image.format == "JPEG"
            assert image.getexif() == {}
            assert image.size == (64, 48)


@pytest.mark.parametrize("bad_image", [
    "not-valid-base64!",
    base64.b64encode(b"not an image").decode("ascii"),
    base64.b64encode(_image_bytes("GIF")).decode("ascii"),
])
def test_invalid_images_rejected_before_provider_call(bad_image):
    provider = FakeFoodProvider()
    with TestClient(create_app(ai_provider=provider)) as client:
        result = client.post("/v1/ai/interpret", json=_request(image_base64=bad_image))
        assert result.status_code == 422
        assert provider.calls == []


def test_direct_image_bytes_limit_and_pixel_bomb_rejection():
    too_big = base64.b64encode(b"a" * 4_000_001).decode("ascii")
    with pytest.raises(InvalidFoodImage, match="4 MB"):
        normalize_image(too_big)
    b = io.BytesIO()
    Image.new("RGB", (4000, 3500)).save(b, format="PNG")
    with pytest.raises(InvalidFoodImage, match="dimensions"):
        normalize_image(base64.b64encode(b.getvalue()).decode("ascii"))


def test_json_body_limit_media_type_and_provider_failure_hidden():
    provider = FakeFoodProvider(fail=True)
    with TestClient(create_app(ai_provider=provider)) as client:
        oversized = client.post("/v1/ai/interpret", content=b"X" * 5_800_001,
                                headers={"Content-Type": "application/json"})
        assert oversized.status_code == 413
        wrong_type = client.post("/v1/ai/interpret", content=b"{}",
                                 headers={"Content-Type": "text/plain"})
        assert wrong_type.status_code == 415
        failed = client.post("/v1/ai/interpret", json=_request())
        assert failed.status_code == 503
        assert "Confidential" not in failed.text
        assert "upstream" not in failed.text


def test_provider_is_governed_by_existing_api_auth():
    provider = FakeFoodProvider()
    with TestClient(create_app(api_key="secret-for-tests", ai_provider=provider)) as client:
        assert client.get("/v1/ai/status").status_code == 401
        assert client.post("/v1/ai/interpret", json=_request()).status_code == 401
        headers = {"X-API-Key": "secret-for-tests"}
        assert client.get("/v1/ai/status", headers=headers).status_code == 200
        assert client.post("/v1/ai/interpret", json=_request(), headers=headers).status_code == 200


def test_process_rate_limit_is_conservative_and_no_requests_bypass():
    provider = FakeFoodProvider()
    with TestClient(create_app(ai_provider=provider)) as client:
        for _ in range(6):
            assert client.post("/v1/ai/interpret", json=_request()).status_code == 200
        response = client.post("/v1/ai/interpret", json=_request())
        assert response.status_code == 429
        assert response.headers["retry-after"] == "60"
        assert len(provider.calls) == 6


def test_openai_adapter_uses_fixed_endpoint_no_storage_and_schema(monkeypatch):
    recorded = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        assert str(request.url) == "https://api.openai.com/v1/responses"
        assert request.headers["authorization"] == "Bearer test-server-secret"
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["model"] == "gpt-6.1-terra"
        assert body["reasoning"] == {"effort": "none"}
        assert "tools" not in body
        assert body["text"]["format"]["strict"] is True
        assert body["input"][0]["content"][1]["type"] == "input_image"
        assert body["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
        text = json.dumps({"search_query": "dumplings", "dishes": ["dumplings"],
                           "cuisines": ["Chinese"], "ingredients": [], "uncertainties": []})
        return httpx.Response(200, json={"status": "completed", "output": [{
            "type": "message", "content": [{"type": "output_text", "text": text}],
        }]})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))
    provider = OpenAIResponsesProvider(api_key="test-server-secret")
    found = asyncio.run(provider.interpret("What is this?", _image_bytes("JPEG")))
    assert found.search_query == "dumplings"
    assert len(recorded) == 1


def test_openai_adapter_rejects_unstructured_or_failed_responses(monkeypatch):
    original = httpx.AsyncClient
    for code, payload in ((429, {"error": "PRIVATE"}), (200, {"status": "incomplete"}),
                          (200, {"status": "completed", "output": []})):
        mock_transport = httpx.MockTransport(
            lambda _request, status=code, body=payload: httpx.Response(status, json=body),
        )
        monkeypatch.setattr(httpx, "AsyncClient", lambda _transport=mock_transport, **kwargs: original(
            transport=_transport, **kwargs))
        with pytest.raises(ProviderUnavailable):
            asyncio.run(OpenAIResponsesProvider(api_key="secret").interpret("noodles", None))


def test_server_ai_is_explicit_opt_in_and_server_only(monkeypatch):
    from savoroute.api.server import serve

    apps = []
    monkeypatch.setenv("SAVOROUTE_BETA_ENABLED", "0")
    monkeypatch.setenv("SAVOROUTE_AI_ENABLED", "1")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SAVOROUTE_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("uvicorn.run", lambda application, **_kwargs: apps.append(application))
    with pytest.raises(ValueError, match="requires SAVOROUTE_OPENAI_API_KEY"):
        serve()
    assert apps == []
    monkeypatch.setenv("SAVOROUTE_OPENAI_API_KEY", "server-secret-test-only")
    serve()
    assert len(apps) == 1
    with TestClient(apps[0]) as client:
        assert client.get("/v1/ai/status").json()["enabled"] is True
        assert "server-secret-test-only" not in client.get("/openapi.json").text
