from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.common.config import Settings
from app.common.observability import observe_provider_call
from app.modules.tree_analyses.provider import (
    PlantAnalysisProvider,
    ProviderError,
    ProviderImage,
    ProviderResult,
    SpeciesCandidate,
    clamp_confidence,
)

DETAILS = "common_names,description,taxonomy,rank,gbif_id,inaturalist_id,image"
logger = logging.getLogger(__name__)
KINDWISE_DETAIL_LANGUAGES = {
    "ar",
    "cs",
    "da",
    "de",
    "en",
    "es",
    "fr",
    "hi",
    "it",
    "ko",
    "nl",
    "pl",
    "pt-BR",
    "sv",
    "tr",
    "zh",
    "zh-hant",
}


class KindwisePlantIdClient(PlantAnalysisProvider):
    """Server-only Plant.id v3 adapter. It never returns provider credentials or tokens."""

    name = "kindwise_plant_id"

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client

    async def analyze(
        self,
        images: list[ProviderImage],
        organs: list[str],
        context: dict[str, Any] | None = None,
    ) -> ProviderResult:
        del organs
        if not self.settings.kindwise_api_key:
            raise ProviderError(
                "ai_provider_misconfigured", "Plant identification is not configured.", 503
            )
        context = context or {}
        location = context.get("location_evidence") or {}
        language = self._provider_language(
            str(context.get("language") or self.settings.kindwise_language)
        )
        data = {
            "latitude": str(location.get("latitude", "")),
            "longitude": str(location.get("longitude", "")),
            "datetime": str(location.get("captured_at", "")),
            "custom_id": str(context["custom_id"]),
            "suggestion_filter": json.dumps(
                {"classification": self.settings.kindwise_suggestion_filter}, separators=(",", ":")
            ),
            "classification_level": self.settings.kindwise_classification_level,
        }
        # Kindwise uses omission—not the string "off"—to disable its optional
        # health assessment. Sending "off" causes a 400 response.
        if self.settings.kindwise_health_mode != "off":
            data["health"] = self.settings.kindwise_health_mode
        files = [
            (f"image{index}", (image.filename, image.content, image.content_type))
            for index, image in enumerate(images, 1)
        ]
        payload = await self._request(
            "POST",
            "/identification",
            params={
                "details": DETAILS,
                "language": language,
            },
            data=data,
            files=files,
        )
        return self.normalize(payload, language)

    async def retrieve(self, custom_id: int) -> ProviderResult | None:
        if not self.settings.kindwise_api_key:
            return None
        language = self._provider_language(self.settings.kindwise_language)
        try:
            payload = await self._request(
                "GET",
                f"/identification/{custom_id}",
                params={"details": DETAILS, "language": language},
            )
        except ProviderError as exc:
            if exc.status_code == 404:
                return None
            raise
        return self.normalize(payload, language)

    def _provider_language(self, requested: str) -> str:
        """Map app locales to a language currently supported by Kindwise details."""
        if requested in KINDWISE_DETAIL_LANGUAGES:
            return requested
        fallback = self.settings.kindwise_fallback_language
        return fallback if fallback in KINDWISE_DETAIL_LANGUAGES else "en"

    async def usage_info(self) -> dict[str, Any]:
        if not self.settings.kindwise_api_key:
            raise ProviderError(
                "ai_provider_misconfigured", "Plant identification is not configured.", 503
            )
        return await self._request("GET", "/usage_info")

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(
            base_url=self.settings.kindwise_base_url.rstrip("/"),
            timeout=httpx.Timeout(self.settings.kindwise_timeout_seconds, connect=5.0),
        )
        close = self._client is None
        started = time.monotonic()
        outcome = "success"
        try:
            try:
                response = await client.request(
                    method,
                    path,
                    headers={"Api-Key": self.settings.kindwise_api_key},
                    **kwargs,
                )
            except httpx.TimeoutException as exc:
                raise ProviderError("request_timeout", "Plant identification timed out.", 504) from exc
            except httpx.RequestError as exc:
                raise ProviderError(
                    "ai_provider_unavailable", "Plant identification is unavailable.", 502
                ) from exc
            self._raise_for_status(response)
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderError(
                    "ai_provider_invalid_response", "Plant identification returned invalid data.", 502
                ) from exc
            if not isinstance(payload, dict):
                raise ProviderError(
                    "ai_provider_invalid_response", "Plant identification returned invalid data.", 502
                )
            return payload
        except ProviderError as exc:
            outcome = exc.code
            raise
        finally:
            observe_provider_call(self.name, "identification", outcome, time.monotonic() - started)
            if close:
                await client.aclose()

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        details = KindwisePlantIdClient._safe_error_details(response)
        logger.warning(
            "kindwise_request_rejected",
            extra={
                "provider_status_code": response.status_code,
                "provider_reason": details.get("provider_reason"),
            },
        )
        if response.status_code in {401, 403}:
            raise ProviderError(
                "ai_provider_misconfigured",
                "Plant identification is unavailable.",
                503,
                details,
            )
        if response.status_code == 404:
            raise ProviderError(
                "analysis_not_found", "Provider result was not found.", 404, details
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    retry_seconds = max(1, int(retry_after))
                except ValueError:
                    retry_seconds = 30
                raise ProviderError(
                    "ai_rate_limited",
                    "Plant identification is temporarily limited.",
                    429,
                    {**details, "retry_after_seconds": retry_seconds},
                )
            raise ProviderError(
                "ai_quota_exceeded",
                "Plant identification quota is unavailable.",
                429,
                details,
            )
        if response.status_code in {408, 504}:
            raise ProviderError(
                "request_timeout", "Plant identification timed out.", 504, details
            )
        if response.status_code >= 500:
            raise ProviderError(
                "ai_provider_unavailable",
                "Plant identification is unavailable.",
                502,
                details,
            )
        raise ProviderError(
            "ai_provider_rejected_input",
            "Plant identification rejected the input.",
            422,
            details,
        )

    @staticmethod
    def _safe_error_details(response: httpx.Response) -> dict[str, Any]:
        details: dict[str, Any] = {"provider_status_code": response.status_code}
        content_type = response.headers.get("content-type", "").casefold()
        reason: str | None = None
        if "json" in content_type:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                candidate = payload.get("detail") or payload.get("message") or payload.get("error")
                if isinstance(candidate, str):
                    reason = candidate
                elif candidate is not None:
                    reason = json.dumps(candidate, separators=(",", ":"), default=str)
            elif isinstance(payload, list):
                reason = json.dumps(payload, separators=(",", ":"), default=str)
        else:
            reason = response.text
        if reason:
            normalized = " ".join(reason.split())
            if normalized and "<html" not in normalized.casefold():
                details["provider_reason"] = normalized[:300]
        return details

    @classmethod
    def normalize(cls, payload: dict[str, Any], preferred_language: str = "en") -> ProviderResult:
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ProviderError(
                "ai_provider_invalid_response", "Plant identification returned invalid data.", 502
            )
        is_plant = result.get("is_plant") or {}
        if not isinstance(is_plant, dict) or not isinstance(is_plant.get("binary"), bool):
            raise ProviderError(
                "ai_provider_invalid_response", "Plant identification returned invalid data.", 502
            )
        suggestions = ((result.get("classification") or {}).get("suggestions") or [])
        candidates: list[SpeciesCandidate] = []
        for suggestion in suggestions[:5]:
            if not isinstance(suggestion, dict) or not suggestion.get("name"):
                continue
            details = suggestion.get("details") or {}
            taxonomy = details.get("taxonomy") or {}
            description = cls._localized(details.get("description"), preferred_language) or {}
            image = details.get("image") or {}
            description_allowed = isinstance(description, dict) and bool(
                description.get("citation")
                or description.get("license_name")
                or description.get("license_url")
            )
            image_allowed = isinstance(image, dict) and bool(
                image.get("citation") or image.get("license_name") or image.get("license_url")
            )
            common_names = cls._localized(details.get("common_names"), preferred_language) or []
            candidates.append(
                SpeciesCandidate(
                    scientific_name=str(suggestion["name"]),
                    common_names=[str(value) for value in common_names],
                    confidence=clamp_confidence(suggestion.get("probability")),
                    provider_taxon_id=str(suggestion.get("id")) if suggestion.get("id") else None,
                    genus=taxonomy.get("genus"),
                    family=taxonomy.get("family"),
                    description=description.get("value") if description_allowed else None,
                    representative_image_url=image.get("value") if image_allowed else None,
                    image_source_url=image.get("citation") if isinstance(image, dict) else None,
                    metadata={
                        "rank": details.get("rank"),
                        "gbif_id": details.get("gbif_id"),
                        "inaturalist_id": details.get("inaturalist_id"),
                        "description_citation": description.get("citation") if isinstance(description, dict) else None,
                        "description_license_name": description.get("license_name") if isinstance(description, dict) else None,
                        "description_license_url": description.get("license_url") if isinstance(description, dict) else None,
                        "image_license_name": image.get("license_name") if isinstance(image, dict) else None,
                        "image_license_url": image.get("license_url") if isinstance(image, dict) else None,
                    },
                )
            )
        health = cls._normalize_health(result)
        return ProviderResult(
            species_candidates=candidates,
            provider_metadata={
                "provider_reference": payload.get("access_token"),
                "model_version": payload.get("model_version"),
            },
            is_plant=bool(is_plant["binary"]),
            is_plant_probability=clamp_confidence(is_plant.get("probability")),
            health=health,
        )

    @staticmethod
    def _localized(value: Any, preferred_language: str) -> Any:
        if not isinstance(value, dict) or "value" in value:
            return value
        if preferred_language in value and value[preferred_language] is not None:
            return value[preferred_language]
        if "en" in value and value["en"] is not None:
            return value["en"]
        return next((item for item in value.values() if item is not None), None)

    @staticmethod
    def _normalize_health(result: dict[str, Any]) -> dict[str, Any] | None:
        is_healthy = result.get("is_healthy")
        if not isinstance(is_healthy, dict) or not isinstance(is_healthy.get("binary"), bool):
            return None
        probability = clamp_confidence(is_healthy.get("probability"))
        if is_healthy["binary"]:
            return {"status": "likely_healthy", "confidence": probability, "summary": None}
        diseases = ((result.get("disease") or {}).get("suggestions") or [])
        usable = [item for item in diseases if isinstance(item, dict) and not item.get("redundant")]
        top = usable[0] if usable else None
        return {
            "status": "possible_issue",
            "confidence": clamp_confidence(top.get("probability")) if top else 1 - probability,
            "summary": (top.get("name") if top else None),
        }


class MockKindwisePlantIdClient(KindwisePlantIdClient):
    """Deterministic fixture provider used by automated tests; never performs network I/O."""

    def __init__(self, result: ProviderResult):
        self.result = result

    async def analyze(self, images, organs, context=None):  # type: ignore[no-untyped-def]
        del images, organs, context
        return self.result

    async def retrieve(self, custom_id: int) -> ProviderResult | None:
        del custom_id
        return self.result
