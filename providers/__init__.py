"""Independent evidence-provider interfaces and implementations."""

from .artwork import ArtworkProvider
from .web_artwork import WebArtworkProvider
from .base import EvidenceProvider
from .stubs import AbilityProvider, ExpansionProvider, HoloProvider, HPProvider

__all__ = ["EvidenceProvider", "ArtworkProvider", "WebArtworkProvider", "HPProvider",
           "AbilityProvider", "ExpansionProvider", "HoloProvider"]
