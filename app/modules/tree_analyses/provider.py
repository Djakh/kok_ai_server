from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ProviderImage:
    content: bytes
    content_type: str
    filename: str


@dataclass(frozen=True)
class SpeciesCandidate:
    scientific_name: str
    common_names: list[str]
    confidence: float
    provider_taxon_id: str | None = None
    genus: str | None = None
    family: str | None = None
    description: str | None = None
    representative_image_url: str | None = None
    image_source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderResult:
    species_candidates: list[SpeciesCandidate]
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    is_plant: bool = True
    is_plant_probability: float | None = None
    health: dict[str, Any] | None = None


class ProviderError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class PlantAnalysisProvider(Protocol):
    name: str

    async def analyze(
        self,
        images: list[ProviderImage],
        organs: list[str],
        context: dict[str, Any] | None = None,
    ) -> ProviderResult: ...

    async def retrieve(self, custom_id: int) -> ProviderResult | None: ...

def clamp_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))
