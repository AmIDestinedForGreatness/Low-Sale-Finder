"""Honest extension seams. These providers deliberately do no inference."""

from .base import EvidenceProvider


class _StubProvider(EvidenceProvider):
    def verify(self, image_path, candidates, context):
        return self.not_checked(
            f"{self.__class__.__name__} is an interface stub; no verifier ran")


class HPProvider(_StubProvider):
    dimension = "hp"


class AbilityProvider(_StubProvider):
    dimension = "ability"


class ExpansionProvider(_StubProvider):
    dimension = "expansion_symbol"


class HoloProvider(_StubProvider):
    dimension = "holo_pattern"
