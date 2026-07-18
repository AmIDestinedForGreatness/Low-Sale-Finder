"""Independent evidence-provider interfaces and implementations."""

from .artwork import ArtworkProvider
from .visual_catalog import VisualCatalogProvider
from .web_artwork import WebArtworkProvider
from .base import EvidenceProvider
from .stubs import AbilityProvider, ExpansionProvider, HoloProvider, HPProvider

__all__ = ["EvidenceProvider", "ArtworkProvider", "VisualCatalogProvider",
           "WebArtworkProvider", "HPProvider", "AbilityProvider",
           "ExpansionProvider", "HoloProvider"]
