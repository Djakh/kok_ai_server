from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any, Literal

import openai
from openai import AsyncOpenAI
from openai.types.responses.easy_input_message_param import EasyInputMessageParam
from openai.types.responses.response_input_content_param import ResponseInputContentParam
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.common.config import Settings
from app.common.observability import observe_provider_call, request_id_context
from app.modules.tree_analyses.provider import (
    PlantAnalysisProvider,
    ProviderError,
    ProviderImage,
    ProviderResult,
    SpeciesCandidate,
    clamp_confidence,
)

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTIONS = """You are the plant/tree identification component of KOK.AI.

Analyze every supplied image together. They are different views of the same candidate tree or
woody plant, not separate specimens. Populate only the supplied structured schema.

Use visible botanical evidence such as leaves, leaf arrangement, bark, trunk, branching, crown
shape, flowers, fruit, and overall structure. Coordinates are supporting evidence only and never
proof of a species. Do not claim certainty when evidence is insufficient and do not invent facts.
Keep the common name, scientific name, genus, and family botanically consistent. Prefer a safer
genus-level identification when species-level evidence is insufficient. Confidence values are
estimates from 0 to 1, rounded to at most two decimal places, and candidates must be ordered from
most to least likely.

Set is_plant=false, candidates=[], and health.status=not_available when the images clearly do not
show an identifiable tree or woody plant, are unusably blurred, or mainly show an unrelated person,
vehicle, building, or indoor object. Do not hallucinate a species. For health, report only visible,
non-diagnostic observations; never assert a serious disease from photographs alone. Use null for
unsupported optional facts.
"""


class OpenAICandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scientific_name: str = Field(min_length=1, max_length=255)
    common_name: str | None
    confidence: float = Field(ge=0, le=1)
    genus: str | None
    family: str | None
    description: str | None


class OpenAIHealth(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["likely_healthy", "possible_issue", "not_available"]
    confidence: float | None = Field(ge=0, le=1)
    summary: str | None


class OpenAIAnalysisOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_plant: bool
    is_plant_confidence: float = Field(ge=0, le=1)
    candidates: list[OpenAICandidate] = Field(max_length=5)
    health: OpenAIHealth


class OpenAIPlantAnalysisProvider(PlantAnalysisProvider):
    """Stateless OpenAI Responses API adapter for provider-neutral tree analysis."""

    name = "openai"

    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None):
        self.settings = settings
        self._client = client or (
            AsyncOpenAI(
                api_key=settings.openai_api_key,
                timeout=settings.openai_timeout_seconds,
                max_retries=0,
            )
            if settings.openai_api_key
            else None
        )

    async def analyze(
        self,
        images: list[ProviderImage],
        organs: list[str],
        context: dict[str, Any] | None = None,
    ) -> ProviderResult:
        if not self.settings.openai_api_key or self._client is None:
            raise ProviderError(
                "ai_provider_misconfigured", "Plant identification is not configured.", 503
            )
        if len(images) != len(organs):
            raise ProviderError(
                "ai_provider_rejected_input", "Plant identification rejected the input.", 422
            )

        context = context or {}
        content: list[ResponseInputContentParam] = [
            {"type": "input_text", "text": self._observation_context(context)}
        ]
        for index, (image, organ) in enumerate(zip(images, organs, strict=True), 1):
            encoded = base64.b64encode(image.content).decode("ascii")
            content.extend(
                [
                    {"type": "input_text", "text": f"Image {index} photo type: {organ}"},
                    {
                        "type": "input_image",
                        "image_url": f"data:{image.content_type};base64,{encoded}",
                        "detail": "high",
                    },
                ]
            )

        started = time.monotonic()
        outcome = "success"
        response_id: str | None = None
        logger.info(
            "openai_tree_analysis_started",
            extra={
                "request_id": request_id_context.get(),
                "provider": self.name,
                "model": self.settings.openai_model,
                "image_count": len(images),
                "photo_types": organs,
                "image_byte_sizes": [len(image.content) for image in images],
            },
        )
        try:
            message: EasyInputMessageParam = {"role": "user", "content": content}
            response = await self._client.responses.create(
                model=self.settings.openai_model,
                instructions=SYSTEM_INSTRUCTIONS,
                input=[message],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "kok_ai_tree_analysis",
                        "description": "Normalized KOK.AI tree identification result.",
                        "schema": OpenAIAnalysisOutput.model_json_schema(),
                        "strict": True,
                    }
                },
                max_output_tokens=self.settings.openai_max_output_tokens,
                store=False,
            )
            response_id = getattr(response, "id", None)
            status = getattr(response, "status", None)
            if status == "incomplete":
                raise ProviderError(
                    "ai_provider_invalid_response",
                    "Plant identification returned incomplete data.",
                    502,
                )
            if self._contains_refusal(response):
                raise ProviderError(
                    "ai_provider_rejected_input",
                    "Plant identification rejected the input.",
                    422,
                )
            output_text = getattr(response, "output_text", "")
            if not output_text:
                raise ProviderError(
                    "ai_provider_invalid_response",
                    "Plant identification returned invalid data.",
                    502,
                )
            try:
                parsed = OpenAIAnalysisOutput.model_validate_json(output_text)
            except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                raise ProviderError(
                    "ai_provider_invalid_response",
                    "Plant identification returned invalid data.",
                    502,
                ) from exc
            result = self._normalize(parsed, response_id)
            logger.info(
                "openai_tree_analysis_completed",
                extra={
                    "request_id": request_id_context.get(),
                    "provider": self.name,
                    "model": self.settings.openai_model,
                    "provider_response_id": response_id,
                    "image_count": len(images),
                    "duration_seconds": time.monotonic() - started,
                    "success": True,
                },
            )
            return result
        except ProviderError as exc:
            outcome = exc.code
            self._log_failure(exc.code, len(images), started, response_id)
            raise
        except Exception as exc:
            mapped = self._map_exception(exc)
            outcome = mapped.code
            self._log_failure(
                mapped.code,
                len(images),
                started,
                getattr(exc, "request_id", None),
            )
            raise mapped from exc
        finally:
            observe_provider_call(
                self.name, "identification", outcome, time.monotonic() - started
            )

    async def retrieve(self, custom_id: int) -> ProviderResult | None:
        # OpenAI calls are stateless (store=false), so there is no remote result to retrieve.
        del custom_id
        return None

    def _normalize(self, output: OpenAIAnalysisOutput, response_id: str | None) -> ProviderResult:
        candidates = [] if not output.is_plant else output.candidates
        health = None
        if output.is_plant and output.health.status != "not_available":
            health = {
                "status": output.health.status,
                "confidence": (
                    clamp_confidence(output.health.confidence)
                    if output.health.confidence is not None
                    else None
                ),
                "summary": output.health.summary,
            }
        return ProviderResult(
            species_candidates=[
                SpeciesCandidate(
                    scientific_name=item.scientific_name,
                    common_names=[item.common_name] if item.common_name else [],
                    confidence=clamp_confidence(item.confidence),
                    genus=item.genus,
                    family=item.family,
                    description=item.description,
                    metadata={"source": "openai_vision"},
                )
                for item in candidates
            ],
            provider_metadata={
                "model": self.settings.openai_model,
                "response_id": response_id,
            },
            is_plant=output.is_plant,
            is_plant_probability=clamp_confidence(output.is_plant_confidence),
            health=health,
        )

    def _observation_context(self, context: dict[str, Any]) -> str:
        location = context.get("location_evidence") or {}
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        language = str(context.get("language") or "en")
        rows = [
            "Identify the single candidate tree using all supplied views together.",
            f"Preferred language for common name and description: {language}.",
        ]
        if latitude is not None and longitude is not None:
            rows.append(
                f"Supporting observation coordinates: latitude={latitude}, longitude={longitude}."
            )
        return "\n".join(rows)

    @staticmethod
    def _contains_refusal(response: Any) -> bool:
        for item in getattr(response, "output", []) or []:
            for part in getattr(item, "content", []) or []:
                part_type = getattr(part, "type", None)
                if part_type == "refusal":
                    return True
                if isinstance(part, dict) and part.get("type") == "refusal":
                    return True
        return False

    @staticmethod
    def _map_exception(exc: Exception) -> ProviderError:
        if isinstance(exc, openai.APITimeoutError):
            return ProviderError("request_timeout", "Plant identification timed out.", 504)
        if isinstance(exc, openai.RateLimitError):
            details: dict[str, Any] = {}
            response = getattr(exc, "response", None)
            retry_after = response.headers.get("retry-after") if response is not None else None
            if retry_after:
                details["retry_after"] = retry_after
            return ProviderError(
                "ai_rate_limited",
                "Plant identification is temporarily limited.",
                429,
                details,
            )
        if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
            return ProviderError(
                "ai_provider_misconfigured", "Plant identification is unavailable.", 503
            )
        if isinstance(exc, openai.BadRequestError | openai.UnprocessableEntityError):
            return ProviderError(
                "ai_provider_rejected_input", "Plant identification rejected the input.", 422
            )
        if isinstance(exc, openai.APIStatusError):
            status_code = getattr(exc, "status_code", 500)
            if status_code >= 500:
                return ProviderError(
                    "ai_provider_unavailable", "Plant identification is unavailable.", 502
                )
            return ProviderError(
                "ai_provider_rejected_input", "Plant identification rejected the input.", 422
            )
        if isinstance(exc, openai.APIConnectionError):
            return ProviderError(
                "ai_provider_unavailable", "Plant identification is unavailable.", 502
            )
        return ProviderError(
            "ai_provider_invalid_response", "Plant identification returned invalid data.", 502
        )

    def _log_failure(
        self,
        code: str,
        image_count: int,
        started: float,
        response_id: str | None = None,
    ) -> None:
        logger.warning(
            "openai_tree_analysis_failed",
            extra={
                "request_id": request_id_context.get(),
                "provider": self.name,
                "model": self.settings.openai_model,
                "image_count": image_count,
                "provider_response_id": response_id,
                "duration_seconds": time.monotonic() - started,
                "success": False,
                "failure_category": code,
            },
        )
