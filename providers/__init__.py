"""Independent evidence-provider interfaces and implementations."""

from .artwork import ArtworkProvider
from .base import EvidenceProvider
from .stubs import AbilityProvider, ExpansionProvider, HoloProvider, HPProvider

__all__ = ["EvidenceProvider", "ArtworkProvider", "HPProvider",
           "AbilityProvider", "ExpansionProvider", "HoloProvider"]
