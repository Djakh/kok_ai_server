# OpenAI tree-analysis provider

## Result

OpenAI Vision temporarily replaces Kindwise as the active tree-identification provider. No Flutter
endpoint, multipart field, response DTO, status flow, tree-registration step, or idempotency rule has
changed. Kindwise remains in the backend and can be selected through configuration.

## Architecture discovered

```text
Flutter multipart request
  -> POST /api/v1/tree-analyses
  -> image signature/decode/size validation and optimization
  -> TreeAnalysisService (idempotency, private storage, persistence)
  -> configured PlantAnalysisProvider
       -> OpenAIPlantAnalysisProvider (active by default), or
       -> KindwisePlantIdClient
  -> ProviderResult (provider-neutral internal DTO)
  -> persisted candidates and normalized KOK.AI response
  -> unchanged AnalysisPayload returned to Flutter
  -> POST /api/v1/trees can register the completed analysis
```

The old raw Kindwise response was never the Flutter contract. `KindwisePlantIdClient.normalize()`
already mapped it to `ProviderResult`; `TreeAnalysisService` then built the stable mobile response.
The OpenAI adapter maps strict model output into that same `ProviderResult`.

## Configuration

All settings use the project's `KOK_` environment prefix:

```dotenv
KOK_PLANT_ANALYSIS_PROVIDER=openai
KOK_OPENAI_API_KEY=your-server-side-project-key
KOK_OPENAI_MODEL=gpt-5.6-luna
KOK_OPENAI_TIMEOUT_SECONDS=30
KOK_OPENAI_MAX_OUTPUT_TOKENS=1800
```

The API key must exist only in the backend environment. Never embed it in Flutter, commit it, print
it, or send it in a client request.

To obtain the key:

1. Sign in to the OpenAI Platform and select or create the backend project.
2. Open <https://platform.openai.com/api-keys> and create a project API key with permission to create
   Responses API requests.
3. Copy the secret when shown and put it directly in the deployed server's secret/environment
   configuration as `KOK_OPENAI_API_KEY`. Do not paste the secret into chat.
4. Ensure the API project has billing/usage available, restart the API, and confirm `/ready` returns
   `{"status":"ready"}`.

To reactivate Kindwise:

```dotenv
KOK_PLANT_ANALYSIS_PROVIDER=kindwise
KOK_KINDWISE_API_KEY=your-kindwise-key
```

Only the selected provider is called. The inactive provider is not used as an automatic fallback,
so one analysis does not incur charges from both providers.

## OpenAI request workflow

1. The existing route accepts 2-5 repeated `photos` and matching repeated `photo_types`. Mobile
   aliases `images` and `organs` remain supported.
2. Existing backend image validation checks the real JPEG/PNG signature, decodes the image, applies
   EXIF orientation, limits pixels/bytes, and optimizes large images.
3. The service stores the original-normalized and provider-optimized versions privately, then calls
   exactly one configured provider.
4. The OpenAI adapter sends every optimized image in one Responses API request as a MIME-correct
   base64 data URL. Each image has an accompanying label such as `Image 1 photo type: whole_tree`.
5. Coordinates and user language are supporting context only. The prompt explicitly prevents using
   location as proof of species.
6. The request uses `detail=high`, no tools or web search, `store=false`, and a strict JSON Schema
   generated from `OpenAIAnalysisOutput`.
7. The adapter validates the returned JSON again with Pydantic, maps it to `ProviderResult`, and the
   existing service persists up to five candidates.
8. `POST /api/v1/trees` consumes the completed analysis exactly as before.

The structured provider result contains only fields needed to populate the existing DTO:

- plant/woody-plant decision and estimated confidence (0-1)
- up to five ordered candidates
- scientific name, nullable common name, confidence, nullable genus/family/description
- health status, nullable confidence, and nullable visible-sign summary

OpenAI does not fabricate Kindwise taxon IDs or source image URLs; those existing mobile fields stay
`null`.

## Compatibility behavior

`tree_analyses.provider_name` records the actual provider (`openai` for new OpenAI analyses), and
`provider_metadata` stores only the model and OpenAI response ID. No migration is required because
both columns were already generic.

For strict backward compatibility, the Flutter-visible `provider` and `attribution.provider_id`
remain `kindwise_plant_id`. This is a compatibility alias because `AnalysisPayload.provider` is an
existing literal field. It can be redesigned only in a separately versioned mobile-contract change.

Example successful mobile response (sanitized):

```json
{
  "success": true,
  "data": {
    "id": "9bf8a2a6-b741-4ff0-94df-9b2310439a87",
    "provider": "kindwise_plant_id",
    "analyzed_at": "2026-09-14T12:00:00Z",
    "candidates": [
      {
        "id": "38436431-24dc-4558-975f-21ca1ec479b1",
        "common_name": "Oriental plane",
        "scientific_name": "Platanus orientalis",
        "confidence": 0.82,
        "genus": "Platanus",
        "family": "Platanaceae",
        "description": "A large deciduous plane tree.",
        "representative_image_url": null,
        "image_source_url": null
      }
    ],
    "species_candidates": [
      {
        "id": "38436431-24dc-4558-975f-21ca1ec479b1",
        "common_name": "Oriental plane",
        "scientific_name": "Platanus orientalis",
        "confidence": 0.82,
        "genus": "Platanus",
        "family": "Platanaceae",
        "description": "A large deciduous plane tree.",
        "representative_image_url": null,
        "image_source_url": null
      }
    ],
    "health": {
      "status": "likely_healthy",
      "confidence": 0.74,
      "summary": "No obvious severe damage is visible."
    },
    "capabilities": {"identification": "available", "health": "available"},
    "attribution": {"provider": "Kindwise Plant.id", "provider_id": "kindwise_plant_id"},
    "uncertainty": {
      "confidence_scale": "0_to_1",
      "candidate_order": "descending_probability",
      "user_confirmation_required": true
    }
  },
  "error": null,
  "meta": null
}
```

## Failure mapping

| Provider condition | KOK.AI error | HTTP |
|---|---|---:|
| Missing/invalid server credentials | `ai_provider_misconfigured` | 503 |
| Timeout | `request_timeout` | 504 |
| Rate limit | `ai_rate_limited` | 429 |
| OpenAI 400/422 | `ai_provider_rejected_input` | 422 |
| OpenAI 5xx/network failure | `ai_provider_unavailable` | 502 |
| Refusal or clear invalid/non-tree model result | existing rejection/no-plant path | 422 |
| Empty, incomplete, or schema-invalid output | `ai_provider_invalid_response` | 502 |

Raw OpenAI messages, authorization data, request images, and base64 data are never returned or
logged. Safe logs include request ID, provider, model, image count, photo types, byte sizes, response
ID, duration, and normalized result category.

## Manual test with two local images

Start the configured API, obtain a normal KOK.AI bearer token, and run:

```bash
export KOKAI_TOKEN='replace-with-login-access-token'
export WHOLE_TREE_IMAGE='/absolute/path/to/whole-tree.jpg'
export LEAF_IMAGE='/absolute/path/to/leaf.jpg'

curl --fail-with-body --request POST 'http://localhost:8000/api/v1/tree-analyses' \
  --header "Authorization: Bearer ${KOKAI_TOKEN}" \
  --header "Idempotency-Key: manual-openai-$(uuidgen)" \
  --form "photos=@${WHOLE_TREE_IMAGE};type=image/jpeg" \
  --form "photos=@${LEAF_IMAGE};type=image/jpeg" \
  --form 'photo_types=whole_tree' \
  --form 'photo_types=leaf' \
  --form 'location_evidence={"latitude":41.2995,"longitude":69.2401,"horizontal_accuracy_meters":5.8,"accepted_sample_count":3,"rejected_sample_count":0,"capture_duration_ms":3000,"best_sample_accuracy_meters":4.2,"captured_at":"2026-09-14T12:00:00Z","quality":"acceptable"}'
```

Use a new idempotency key when intentionally starting a new paid analysis. Retrying the same request
with the same key preserves the existing no-duplicate behavior.
