"""Shared seam for independent evidence backends."""


class EvidenceProvider:
    dimension = "unknown"

    def verify(self, image_path, candidates, context):
        raise NotImplementedError

    def not_checked(self, note):
        return {"provider": self.__class__.__name__, "dimension": self.dimension,
                "status": "not_checked", "note": note}
