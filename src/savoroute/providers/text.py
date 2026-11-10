"""Optional text-generation adapters for the extraction protocol."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    """Remote or local model request failed."""


class OpenAITextGenerator:
    """Uses the OpenAI Responses API; requires the optional `openai` extra."""

    def __init__(self, model_id: str, *, client=None):
        if not model_id.strip():
            raise ValueError("model_id must not be empty")
        self.model_id = model_id
        if client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise ProviderError('Install the provider extra: pip install -e ".[openai]"') from exc
            if not os.environ.get("OPENAI_API_KEY"):
                raise ProviderError("OPENAI_API_KEY is not set")
            client = OpenAI(timeout=30.0, max_retries=0)
        self._client = client

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        response = self._client.responses.create(
            model=self.model_id, instructions=system_prompt, input=user_prompt,
        )
        output = response.output_text
        if not isinstance(output, str) or not output.strip():
            raise ProviderError("model response contains no output text")
        return output


class OllamaTextGenerator:
    """Uses a locally hosted Ollama /api/generate endpoint with JSON output format."""

    def __init__(self, model_id: str, *, base_url: str = "http://127.0.0.1:11434"):
        if not model_id.strip():
            raise ValueError("model_id must not be empty")
        parsed = urlparse(base_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment or
                (parsed.path not in ("", "/"))):
            raise ValueError("base_url must be an HTTP(S) origin without credentials or path")
        self.model_id = model_id
        self.base_url = base_url.rstrip("/")

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        body = json.dumps({
            "model": self.model_id, "system": system_prompt, "prompt": user_prompt,
            "format": "json", "stream": False, "options": {"temperature": 0},
        }).encode("utf-8")
        request = Request(
            self.base_url + "/api/generate", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urlopen(request, timeout=90) as response:
                payload = response.read(1_000_001)
                if len(payload) > 1_000_000:
                    raise ProviderError("Ollama response exceeds 1 MB")
                result = json.loads(payload)
        except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError,
                UnicodeDecodeError) as exc:
            raise ProviderError(f"Ollama request failed ({type(exc).__name__})") from exc
        if not isinstance(result, dict) or not isinstance(result.get("response"), str):
            raise ProviderError("Ollama response lacks a text result")
        return result["response"]
