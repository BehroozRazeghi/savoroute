"""Future provider capabilities (interfaces only; no network implementations)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol


class TextGenerator(Protocol):
    model_id: str

    def generate(self, *, system_prompt: str, user_prompt: str) -> str: ...


class VisionCaptioner(Protocol):
    model_id: str

    def caption(self, image_path: Path, *, context: str = "") -> str: ...


class TextEmbedder(Protocol):
    model_id: str

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...


class JointTextImageEmbedder(Protocol):
    """Text/image vectors share the same embedding_space_id and dimensions."""

    model_id: str
    embedding_space_id: str

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_images(self, paths: Sequence[Path]) -> list[list[float]]: ...
