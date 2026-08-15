# Tree Registration Integration

## Scope
This document covers the tree registration flow after backend integration of the minimal tree detector.

The registration API contract is unchanged:
- `POST /api/v1/trees/register`
- `GET /api/v1/trees`
- `GET /api/v1/trees/{tree_id}`

The backend now adds optional AI-analysis metadata to tree responses.

## Registration Flow
Frontend still has two supported flows:

1. Multipart upload in one request
2. JSON metadata using previously uploaded asset IDs

Required tree registration payload remains:

```json
{
  "name": "Oak near park",
  "location": {
    "latitude": 41.2995,
    "longitude": 69.2401,
    "accuracy_meters": 5
  },
  "images": {
    "front": "upload-id-1",
    "trunk": "upload-id-2",
    "leaves": "upload-id-3"
  },
  "captured_at": "2026-03-31T09:30:00Z"
}
```

## New Response Field
All tree payloads may now include:

```json
"ai_analysis": {
  "status": "queued|completed|failed|skipped",
  "model_version": "treedetect.pt",
  "analyzed_at": "2026-03-31T09:31:10Z",
  "summary": {
    "tree_detected": true,
    "images_with_detections": 3,
    "max_confidence": 0.9821,
    "images": {
      "front": {
        "detected": true,
        "boxes_count": 1,
        "max_confidence": 0.9821
      },
      "trunk": {
        "detected": true,
        "boxes_count": 1,
        "max_confidence": 0.9532
      },
      "leaves": {
        "detected": true,
        "boxes_count": 1,
        "max_confidence": 0.9444
      }
    }
  }
}
```

## Frontend Handling Rules
- Treat `ai_analysis` as optional.
- Do not block registration on AI status.
- Right after registration, expect `ai_analysis.status` to be `queued`.
- Poll tree detail or refresh list later if UI needs completed analysis.
- If `status` is `failed` or `skipped`, show nothing or a non-blocking hint. Do not treat it as a fatal registration error.

## Suggested UI Copy
- `queued`: `Photo analysis in progress`
- `completed`: `Photo analysis complete`
- `failed`: `Photo analysis unavailable`
- `skipped`: `Photo analysis disabled`

## Seed Data
Local seed users:
- `alice@example.com` / `Passw0rd123`
- `bob@example.com` / `Passw0rd123`
- `clara@example.com` / `Passw0rd123`

Seeded trees include AI-analysis examples:
- one tree with `completed`
- one tree with `skipped`

## Platform Base URLs
- iOS Simulator: `http://localhost:8000/api/v1`
- Android Emulator: `http://10.0.2.2:8000/api/v1`
- Physical Android device: `http://<your-mac-local-ip>:8000/api/v1`

## Important Notes
- The detector runs asynchronously in Celery after tree creation.
- Registration success does not mean AI analysis has finished.
- Local Flutter file paths must never be stored as final image references.
- Blank optional query params should be omitted from URLs, not sent as empty keys.
