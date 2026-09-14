# Create Tree and Kindwise Workflow

This is the implementation contract for mobile clients that identify and create a tree. It
documents the API as implemented in this repository.

## Verification status

Verified on 2026-09-13:

- repository lint and static type checking pass;
- the full suite collects 65 tests and completes with 63 passing and 2 PostgreSQL integration
  tests skipped because PostgreSQL/Docker is not reachable from the test process;
- the application generates an OpenAPI document with the tree-analysis and tree routes loaded;
- the configured Kindwise key authenticates against the live `/usage_info` endpoint and the
  account reports that it is active and can use credits;
- Kindwise request construction, normalization, failure mapping, health-mode behavior, timeout
  recovery, and idempotency are covered with non-billable mocked HTTP/provider tests.

A paid live photo-identification request was intentionally not submitted during verification.
Run one staging identification with known tree images before a production release to validate the
complete network, storage, quota, and provider-result path in that environment.

## Contract summary

- API prefix: `/api/v1`
- Authentication: `Authorization: Bearer <access-token>` on every endpoint below
- Response envelope: `{ "success": true, "data": ..., "error": null, "meta": ... }`
- Error envelope: `{ "success": false, "data": null, "error": { "code": ..., "message": ...,
  "request_id": ..., "details": ... }, "meta": null }`
- Mobile never calls Kindwise directly and must never contain the Kindwise API key.
- Identification is advisory. A user must select a candidate or provide a correction before the
  app treats a species as confirmed.
- The canonical flow is:

```text
capture photos and GPS
        |
        v
POST /tree-analyses  -- backend calls Kindwise Plant.id
        |
        v
show candidates and require user confirmation
        |
        v
GET /trees/nearby    -- show possible duplicates
        |
        v
POST /trees          -- atomically creates the tree
        |
        v
GET /trees/{tree_id} -- refresh detail and signed photo URLs
```

## 1. Capture requirements

Collect 2–5 JPEG or PNG files. The request must contain exactly one whole-tree photo and exactly
one leaf photo. Each optional type may occur at most once.

Accepted categories are:

- `auto` (mobile alias that the backend converts to `whole_tree`)
- `whole_tree`
- `leaf`
- `bark`
- `flower_or_fruit`
- `additional`

The normal three-photo mobile capture is `auto`, `bark`, `leaf`, aligned by index with the three
files. Do not send duplicate categories. Each file is limited to 15 MiB (15,728,640 bytes), the
combined image content to 40,000,000 bytes, and a decoded source to 40 megapixels. Animated or malformed
files are rejected. The backend applies EXIF orientation, keeps a normalized original, and creates
a display copy of at most 2 megapixels. Mobile should target much smaller files; see
[MOBILE_IMAGE_OPTIMIZATION_PROMPT.md](MOBILE_IMAGE_OPTIMIZATION_PROMPT.md).

Capture location at the same time as the photos. Prefer the full evidence object because it lets
the backend preserve GPS quality and sampling information:

```json
{
  "latitude": 41.299503,
  "longitude": 69.240098,
  "horizontal_accuracy_meters": 5.8,
  "accepted_sample_count": 8,
  "rejected_sample_count": 2,
  "capture_duration_ms": 12000,
  "best_sample_accuracy_meters": 4.2,
  "captured_at": "2026-09-13T05:00:12Z",
  "quality": "acceptable"
}
```

`captured_at` must be ISO 8601 with a timezone. Quality is `excellent`, `acceptable`, or `poor`.

## 2. Analyze the photos

### Request

`POST /api/v1/tree-analyses`

Content type is `multipart/form-data`. Generate one UUID and send it as `Idempotency-Key`. Keep
the same key only while retrying the exact same photos, categories, and location evidence.

Recommended rich form:

```text
photos=<whole-tree.jpg>                 repeated binary field
photos=<bark.jpg>
photos=<leaf.jpg>
photo_types=whole_tree                  repeated text field, same order as photos
photo_types=bark
photo_types=leaf
location_evidence={...JSON object above...}
```

The compact mobile aliases are also supported:

```text
images=<whole-tree.jpg>                 repeated binary field
images=<bark.jpg>
images=<leaf.jpg>
organs=auto                             repeated text field, same order as images
organs=bark
organs=leaf
latitude=41.299503
longitude=69.240098
accuracy_meters=5.8                     optional
captured_at=2026-09-13T05:00:12Z        optional
```

Do not mix `photos` with `images`, or `photo_types` with `organs`. If only scalar coordinates are
sent, the backend creates reduced-quality evidence; the full evidence form is preferred.

### Success response

The first successful request returns `201`. An exact completed replay returns `200` and
`meta.idempotency_replayed=true`.

```json
{
  "success": true,
  "data": {
    "id": "8a3f0ca0-d4d1-4ba1-b65e-918b16eec918",
    "provider": "kindwise_plant_id",
    "analyzed_at": "2026-09-13T05:00:25Z",
    "candidates": [
      {
        "id": "7d351461-792e-4735-9274-4833bf2c99f4",
        "common_name": "Oriental plane",
        "scientific_name": "Platanus orientalis",
        "confidence": 0.87,
        "genus": "Platanus",
        "family": "Platanaceae",
        "description": null,
        "representative_image_url": null,
        "image_source_url": null
      }
    ],
    "species_candidates": [
      {
        "id": "7d351461-792e-4735-9274-4833bf2c99f4",
        "common_name": "Oriental plane",
        "scientific_name": "Platanus orientalis",
        "confidence": 0.87,
        "genus": "Platanus",
        "family": "Platanaceae",
        "description": null,
        "representative_image_url": null,
        "image_source_url": null
      }
    ],
    "health": {
      "status": "not_available",
      "confidence": null,
      "summary": null
    },
    "capabilities": {
      "identification": "available",
      "health": "not_available"
    },
    "attribution": {
      "provider": "Kindwise Plant.id",
      "provider_id": "kindwise_plant_id"
    },
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

`candidates` and `species_candidates` contain the same list; mobile may read either, but should
standardize on `candidates`. At most five candidates are returned in descending provider order.
Confidence is a number from 0 to 1, not a percentage. Candidate `id` is the backend UUID required
for confirmation; it is not the Kindwise taxon ID.

The app must present uncertainty and require an explicit choice. It must not silently select the
top result.

### Retrieve an analysis

`GET /api/v1/tree-analyses/{analysis_id}` is owner-only. Use it to recover state after an
interrupted client request. A completed response has the same data shape as the POST response.

An analysis can be used to create only one tree and expires after `KOK_ANALYSIS_TTL_HOURS`
(24 hours by default).

## 3. Review nearby trees

Before creation call:

```http
GET /api/v1/trees/nearby?latitude=41.299503&longitude=69.240098&radius_meters=20&scientific_name=Platanus%20orientalis
```

`radius_meters` must be greater than 0 and no more than 100. `scientific_name` is optional and is
matched case-insensitively. The response includes the current user's private trees plus public
trees owned by other users. Every item includes `tree_id`, `distance_meters`,
`horizontal_accuracy_meters`, identification, and display-image fields.

Nearby results never auto-merge or block creation. Show them to the user and record the outcome:

- `noNearbyTrees`: no candidates were returned.
- `possibleMatches`: candidates were shown and the user chose to create a new tree.
- `skippedDueToNetworkFailure`: lookup failed and the product explicitly permits continuing.

If the user selects an existing tree, navigate to it and do not call `POST /trees`.

## 4. Create the tree

### Request

`POST /api/v1/trees`

Content type is `application/json`. Use a new UUID for `Idempotency-Key`; never reuse the analysis
key for this operation.

Candidate confirmation:

```json
{
  "analysis_id": "8a3f0ca0-d4d1-4ba1-b65e-918b16eec918",
  "confirmed_species": {
    "id": "7d351461-792e-4735-9274-4833bf2c99f4",
    "scientific_name": "Platanus orientalis",
    "common_name": "Oriental plane"
  },
  "location_evidence": {
    "latitude": 41.299503,
    "longitude": 69.240098,
    "horizontal_accuracy_meters": 5.8,
    "accepted_sample_count": 8,
    "rejected_sample_count": 2,
    "capture_duration_ms": 12000,
    "best_sample_accuracy_meters": 4.2,
    "captured_at": "2026-09-13T05:00:12Z",
    "quality": "acceptable"
  },
  "duplicate_check_status": "possibleMatches",
  "nickname": "School plane",
  "notes": "North gate",
  "visibility": "private"
}
```

For a user correction that is not one of the candidates, omit `confirmed_species` and send:

```json
{
  "analysis_id": "8a3f0ca0-d4d1-4ba1-b65e-918b16eec918",
  "manual_scientific_name": "Platanus orientalis",
  "location_evidence": {
    "latitude": 41.299503,
    "longitude": 69.240098,
    "horizontal_accuracy_meters": 5.8,
    "accepted_sample_count": 8,
    "rejected_sample_count": 2,
    "capture_duration_ms": 12000,
    "best_sample_accuracy_meters": 4.2,
    "captured_at": "2026-09-13T05:00:12Z",
    "quality": "acceptable"
  }
}
```

Compatibility fields `selected_candidate_id`, `latitude`, `longitude`, `accuracy_meters`, and
`captured_at` are supported, but new mobile code should use `confirmed_species` plus full
`location_evidence`.

Rules enforced by the backend:

- The authenticated user must own the completed, unexpired analysis.
- The analysis must not already be attached to another tree.
- A candidate ID must belong to that analysis. The stored candidate species is authoritative;
  client-supplied candidate labels cannot replace it.
- Candidate selection and `manual_scientific_name` are mutually exclusive.
- Creation location must remain close to the analysis location. Allowed drift is the larger of
  10 meters or the sum of the two reported horizontal accuracies.
- `visibility` is `private` or `public` and defaults to `private`.
- `nickname` is 1–120 characters; `notes` is at most 2,000 characters.

### What the backend creates

The operation commits the following together:

- a tree owned by the authenticated user, initially `pending` rather than moderator-verified;
- the selected or manually corrected species and its provenance;
- immutable capture location and GPS-quality evidence;
- an initial scan linked to the analysis;
- a registration event and an outbox event;
- a completed idempotency record containing the replay response.

The tree and initial scan use the photo/GPS `captured_at`; Kindwise completion remains separately
available as the analysis/scan `analyzed_at`.

### Success response

Initial success returns `201`. An exact retry after completion returns `200` with the same tree
data. Important fields are:

```json
{
  "success": true,
  "data": {
    "id": "tree-uuid",
    "nickname": "School plane",
    "owner_id": "user-uuid",
    "registered_at": "2026-09-13T05:00:26Z",
    "last_scanned_at": "2026-09-13T05:00:25Z",
    "primary_image_url": "https://api.example.com/api/v1/media/tree-analysis/...",
    "photos": [
      {"type": "whole_tree", "url": "https://api.example.com/api/v1/media/tree-analysis/..."},
      {"type": "bark", "url": "https://api.example.com/api/v1/media/tree-analysis/..."},
      {"type": "leaf", "url": "https://api.example.com/api/v1/media/tree-analysis/..."}
    ],
    "location": {
      "latitude": 41.299503,
      "longitude": 69.240098,
      "horizontal_accuracy_meters": 5.8,
      "accuracy_meters": 5.8,
      "captured_at": "2026-09-13T05:00:12Z",
      "quality": "acceptable"
    },
    "identification": {
      "common_name": "Oriental plane",
      "scientific_name": "Platanus orientalis",
      "ai_confidence": 0.87,
      "ai_provider": "kindwise_plant_id",
      "source": "user_confirmed_ai",
      "description": null
    },
    "confirmed_species": {
      "scientific_name": "Platanus orientalis",
      "common_name": "Oriental plane"
    },
    "visibility": "private",
    "health": {"status": "not_available", "confidence": null, "summary": null},
    "latest_health": {"status": "not_available"},
    "notes": "North gate",
    "created_at": "2026-09-13T05:00:26Z",
    "updated_at": "2026-09-13T05:00:26Z"
  },
  "error": null,
  "meta": null
}
```

Save `data.id` as the tree ID. Then call `GET /api/v1/trees/{id}` for the authoritative detail.
Analysis-backed photo URLs are signed API URLs valid for approximately 15 minutes. Treat them as
opaque: do not build, edit, or persist them as permanent identifiers. Refresh tree detail when a
URL expires. The API streams the private object; it does not expose MinIO/S3 credentials or an
internal host name.

## 5. Kindwise integration behind the API

The backend maps the analysis request to Kindwise Plant.id v3 as follows:

| Backend value | Kindwise request |
| --- | --- |
| normalized JPEG/PNG files | multipart images on `POST /api/v3/identification` |
| latitude / longitude | multipart `latitude` / `longitude` |
| evidence `captured_at` | multipart `datetime` |
| numeric analysis reference | multipart `custom_id` for timeout recovery |
| configured tree filter | `suggestion_filter={"classification":"tree"}` |
| species candidates | `classification_level=species` |
| descriptions/taxonomy/images | `details` query parameter |
| supported detail locale | `language` query parameter |

Authentication uses the server-side `Api-Key` header. The provider access token, API key, and raw
provider response are never returned to mobile and the raw response is not persisted. The backend
stores only normalized candidates, licensed detail/image fields when attribution metadata exists,
plant probability, health summary, model version, and its own IDs.

The app supports `en`, `ru`, and `uz`. Kindwise detail localization currently does not support
Russian or Uzbek, so those app locales intentionally request the configured English fallback from
Kindwise. This does not change the app's own UI locale.

Health analysis is off by default. In that mode the backend omits Kindwise's optional `health`
field and returns `health.status=not_available`. `KOK_KINDWISE_HEALTH_MODE=auto` or `all` enables
the provider feature and may consume additional credits. Mobile must use `capabilities.health` and
must never infer health from species confidence.

Kindwise can finish a request after the backend times out. The backend therefore sends a unique
numeric `custom_id`; after a timeout it performs one retrieval by that ID before returning an
error. Idempotency prevents a mobile retry from starting a second paid analysis for the same key
and content.

Provider reference: [Plant.id v3 documentation](https://plant.id/docs) and the
[official OpenAPI specification](https://plant.id/api/v3/openapi.yaml).

## 6. Error and retry behavior

Always branch on `error.code`, not on the English message.

| HTTP | Common code | Mobile behavior |
| --- | --- | --- |
| 401 | `unauthorized` | Refresh/login, then retry with the same idempotency key. |
| 409 | `idempotency_conflict` | Programming/state error: the key was reused for different input. Generate a key only for a genuinely new operation. |
| 409 | `request_in_progress` | Poll `GET /tree-analyses/{id}` when an analysis ID is supplied; do not create another paid request. |
| 409 | `invalid_state` | Use the already-created tree or restart the flow with a new analysis. |
| 413 | `upload_too_large` | Resize/recompress and begin a new analysis with a new key. |
| 415/422 | `invalid_image`, `image_decode_failed`, `invalid_image_dimensions`, `invalid_image_count` | Correct capture/input and begin a new analysis. |
| 422 | `no_plant_detected` | Ask the user to retake clear tree/leaf photos. The error details include `analysis_id`. |
| 422 | `invalid_location_evidence` | Recapture GPS or return to the original location. |
| 422 | `ai_provider_rejected_input` | Inspect `details.provider_status_code` and optional safe `details.provider_reason`; correct the indicated input and start a new analysis with a new key. |
| 429 | `ai_rate_limited` | Respect `Retry-After`; retry the exact request with the same key. |
| 429 | `ai_quota_exceeded` | Show temporary unavailability; do not loop retries. |
| 502/503/504 | `ai_provider_unavailable`, `ai_provider_misconfigured`, `backend_unavailable`, `request_timeout` | Show retry UI. Reuse the same key for the unchanged request. |

Before generating a replacement idempotency key, determine whether the logical action or any
photos/location changed. Network retry of unchanged input must keep the original key.

## 7. Mobile implementation checklist

- Use a publicly reachable HTTPS value for the backend base URL on a physical device.
- Store no Kindwise secret or provider access token in the app.
- Send aligned repeated multipart fields; verify file count equals category count.
- Capture timezone-aware GPS evidence at photo time.
- Persist the analysis ID and both idempotency keys until creation finishes.
- Display candidate confidence as uncertainty and require explicit confirmation.
- Perform and display nearby duplicate review before creation.
- Save only the returned tree ID; treat all media URLs as opaque and refreshable.
- Preserve `error.request_id` in client logs and support reports.
- Do not retry 4xx validation/no-plant errors automatically.
- Retry transient failures with backoff and the same idempotency key.
