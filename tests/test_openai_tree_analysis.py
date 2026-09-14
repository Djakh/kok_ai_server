import json
import logging
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx2
import openai
import pytest

import app.modules.tree_analyses.dependencies as analysis_dependencies
from app.common.config import Settings
from app.modules.tree_analyses.kindwise import KindwisePlantIdClient
from app.modules.tree_analyses.openai_provider import OpenAIPlantAnalysisProvider
from app.modules.tree_analyses.provider import ProviderError, ProviderImage
from app.modules.tree_analyses.router import mobile_analysis_payload
from app.modules.tree_analyses.schemas import AnalysisPayload


def _image(value: bytes = b"jpeg-data") -> ProviderImage:
    return ProviderImage(value, "image/jpeg", "tree.jpg")


def _success_json(*, is_plant: bool = True) -> str:
    return json.dumps(
        {
            "is_plant": is_plant,
            "is_plant_confidence": 0.91 if is_plant else 0.05,
            "candidates": (
                [
                    {
                        "scientific_name": "Platanus orientalis",
                        "common_name": "Oriental plane",
                        "confidence": 0.82,
                        "genus": "Platanus",
                        "family": "Platanaceae",
                        "description": "A large deciduous plane tree.",
                    }
                ]
                if is_plant
                else []
            ),
            "health": {
                "status": "likely_healthy" if is_plant else "not_available",
                "confidence": 0.74 if is_plant else None,
                "summary": "No obvious severe damage is visible." if is_plant else None,
            },
        }
    )


class FakeResponses:
    def __init__(self, response=None, error: Exception | None = None):  # noqa: ANN001
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    async def create(self, **kwargs):  # noqa: ANN003
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response


def _provider(responses: FakeResponses) -> OpenAIPlantAnalysisProvider:
    client = SimpleNamespace(responses=responses)
    return OpenAIPlantAnalysisProvider(
        Settings(_env_file=None, openai_api_key="test-secret", openai_model="gpt-5.6-luna"),
        client,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_openai_sends_all_images_once_with_types_and_strict_schema(caplog) -> None:
    responses = FakeResponses(
        SimpleNamespace(
            id="resp_test_123",
            status="completed",
            output_text=_success_json(),
            output=[],
        )
    )
    provider = _provider(responses)

    with caplog.at_level(logging.INFO):
        result = await provider.analyze(
            [_image(b"whole-tree"), _image(b"leaf")],
            ["whole_tree", "leaf"],
            {
                "language": "uz",
                "location_evidence": {"latitude": 41.3, "longitude": 69.2},
            },
        )

    assert len(responses.calls) == 1
    request = responses.calls[0]
    assert request["model"] == "gpt-5.6-luna"
    assert request["store"] is False
    assert "tools" not in request
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["text"]["format"]["strict"] is True
    assert request["text"]["format"]["schema"]["additionalProperties"] is False
    content = request["input"][0]["content"]
    assert [part["type"] for part in content].count("input_image") == 2
    labels = [part["text"] for part in content if part["type"] == "input_text"]
    assert any("whole_tree" in label for label in labels)
    assert any("leaf" in label for label in labels)
    assert all(part["detail"] == "high" for part in content if part["type"] == "input_image")
    assert result.species_candidates[0].scientific_name == "Platanus orientalis"
    assert result.species_candidates[0].confidence == 0.82
    assert result.provider_metadata == {
        "model": "gpt-5.6-luna",
        "response_id": "resp_test_123",
    }
    assert "test-secret" not in caplog.text
    assert "base64" not in caplog.text
    assert "whole-tree" not in caplog.text


@pytest.mark.asyncio
async def test_openai_no_tree_result_is_normalized_without_candidates() -> None:
    responses = FakeResponses(
        SimpleNamespace(id="resp_no_tree", status="completed", output_text=_success_json(is_plant=False), output=[])
    )
    result = await _provider(responses).analyze([_image()], ["whole_tree"])

    assert result.is_plant is False
    assert result.is_plant_probability == 0.05
    assert result.species_candidates == []
    assert result.health is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "code", "status_code"),
    [
        (
            SimpleNamespace(
                id="resp_incomplete", status="incomplete", output_text="", output=[]
            ),
            "ai_provider_invalid_response",
            502,
        ),
        (
            SimpleNamespace(
                id="resp_refusal",
                status="completed",
                output_text="",
                output=[SimpleNamespace(content=[SimpleNamespace(type="refusal")])],
            ),
            "ai_provider_rejected_input",
            422,
        ),
        (
            SimpleNamespace(
                id="resp_invalid", status="completed", output_text="not-json", output=[]
            ),
            "ai_provider_invalid_response",
            502,
        ),
    ],
)
async def test_openai_invalid_refusal_and_incomplete_mapping(response, code, status_code) -> None:  # noqa: ANN001
    with pytest.raises(ProviderError) as exc_info:
        await _provider(FakeResponses(response)).analyze([_image()], ["whole_tree"])
    assert exc_info.value.code == code
    assert exc_info.value.status_code == status_code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code", "status_code"),
    [
        (
            openai.APITimeoutError(request=httpx2.Request("POST", "https://api.openai.com")),
            "request_timeout",
            504,
        ),
        (
            openai.APIConnectionError(
                request=httpx2.Request("POST", "https://api.openai.com")
            ),
            "ai_provider_unavailable",
            502,
        ),
        (
            openai.RateLimitError(
                "limited",
                response=httpx2.Response(
                    429,
                    headers={"retry-after": "7"},
                    request=httpx2.Request("POST", "https://api.openai.com"),
                ),
                body=None,
            ),
            "ai_rate_limited",
            429,
        ),
        (
            openai.BadRequestError(
                "bad",
                response=httpx2.Response(
                    400, request=httpx2.Request("POST", "https://api.openai.com")
                ),
                body=None,
            ),
            "ai_provider_rejected_input",
            422,
        ),
        (
            openai.InternalServerError(
                "down",
                response=httpx2.Response(
                    500, request=httpx2.Request("POST", "https://api.openai.com")
                ),
                body=None,
            ),
            "ai_provider_unavailable",
            502,
        ),
    ],
)
async def test_openai_sdk_failures_are_safely_mapped(error, code, status_code, caplog) -> None:  # noqa: ANN001
    with caplog.at_level(logging.WARNING), pytest.raises(ProviderError) as exc_info:
        await _provider(FakeResponses(error=error)).analyze([_image()], ["whole_tree"])
    assert exc_info.value.code == code
    assert exc_info.value.status_code == status_code
    assert "test-secret" not in caplog.text
    assert "base64" not in caplog.text


def test_provider_selection_is_centralized(monkeypatch) -> None:
    analysis_dependencies.get_plant_analysis_provider.cache_clear()
    monkeypatch.setattr(
        analysis_dependencies,
        "get_settings",
        lambda: Settings(_env_file=None, plant_analysis_provider="openai", openai_api_key="x"),
    )
    assert isinstance(
        analysis_dependencies.get_plant_analysis_provider(), OpenAIPlantAnalysisProvider
    )

    analysis_dependencies.get_plant_analysis_provider.cache_clear()
    monkeypatch.setattr(
        analysis_dependencies,
        "get_settings",
        lambda: Settings(
            _env_file=None, plant_analysis_provider="kindwise", kindwise_api_key="x"
        ),
    )
    assert isinstance(analysis_dependencies.get_plant_analysis_provider(), KindwisePlantIdClient)
    analysis_dependencies.get_plant_analysis_provider.cache_clear()


def test_openai_and_kindwise_share_unchanged_mobile_schema() -> None:
    candidate_id = uuid.uuid4()
    analyzed_at = datetime.now(timezone.utc)
    common_candidate = {
        "id": str(candidate_id),
        "common_name": "Oriental plane",
        "scientific_name": "Platanus orientalis",
        "confidence": 0.82,
        "genus": "Platanus",
        "family": "Platanaceae",
        "description": "A large deciduous plane tree.",
        "representative_image_url": None,
        "image_source_url": None,
    }
    legacy_result = {
        "id": str(uuid.uuid4()),
        "provider": "kindwise_plant_id",
        "analyzed_at": analyzed_at,
        "candidates": [common_candidate],
        "species_candidates": [common_candidate],
        "health": {"status": "not_available", "confidence": None, "summary": None},
    }
    openai_normalized_result = dict(legacy_result)

    kindwise_payload = mobile_analysis_payload(legacy_result)
    openai_payload = mobile_analysis_payload(openai_normalized_result)
    assert kindwise_payload.keys() == openai_payload.keys()
    assert AnalysisPayload.model_validate(kindwise_payload).model_dump().keys() == (
        AnalysisPayload.model_validate(openai_payload).model_dump().keys()
    )
