"""Verify import-time behavior is lightweight and provider-free."""

from savoroute import __version__
from savoroute.data.catalog import load_catalog
from savoroute.providers.contracts import (
    JointTextImageEmbedder,
    TextEmbedder,
    TextGenerator,
    VisionCaptioner,
)


def test_version_and_bundled_data():
    assert __version__ == "0.6.0"
    assert load_catalog().synthetic is True


def test_provider_contracts_are_separate():
    for capability in (TextGenerator, VisionCaptioner, TextEmbedder, JointTextImageEmbedder):
        assert hasattr(capability, "__dict__")
