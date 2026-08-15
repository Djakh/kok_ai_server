# KOK.AI backend implementation report

Date: 2026-08-15

## Implemented

- Standard success/error envelope with snake_case `request_id` and lowercase stable codes.
- Kindwise Plant.id v3 server adapter with `Api-Key`, configured details/locales, tree filter, species classification, health mode, five-image support, safe error mapping, and timeout recovery lookup by numeric `custom_id`.
- Exact 2–5 repeated `photos`/`photo_types` multipart contract and full JSON `location_evidence` validation.
- JPEG/PNG signature/decode validation, orientation normalization, EXIF removal, size/pixel limits, digests, generated object keys, and categorized image persistence.
- Separate high-quality normalized originals and up-to-2 MP provider/display derivatives, upload dimensions/digests/status/expiry, signed private URLs, and scheduled abandoned-upload cleanup.
- No-plant as `422 no_plant_detected`; empty and low-confidence candidates remain successful without rescaling probabilities.
- Normalized candidate persistence with provider taxon ID, taxonomy, citations/licenses, and mobile-safe fields. Raw provider JSON and provider access tokens are not stored or returned.
- Analysis retrieval and durable, request-fingerprinted analysis idempotency.
- PostGIS nearby suggestions with privacy filtering, metre distances, radius cap, and no automatic merge.
- Idempotent tree creation with AI/manual/unknown selection, immutable analysis evidence, location consistency check, duplicate-check status, visibility, and durable DB replay records.
- Tree list/search/sorts, detail, scan history/create, and moderator-only verification compatibility.
- Argon2id passwords, refresh hashing/rotation, family reuse revocation, `sid`/`jti` claims, and `expires_in`.
- Production fail-closed Kindwise configuration, health/readiness/version routes, metrics, migration, and updated local/deployment documentation.
- Scheduled Kindwise usage/credit metrics and a transactional outbox for tree-registration follow-up work.

## Compatibility

Legacy `/api/v1/trees/register` and the secondary social/profile/upload/notification modules remain available. The new mobile client must use the analysis → nearby → tree flow and the snake_case fields described by the supplied mobile contract.

## Verification

Automated tests use mocked provider responses only. Ruff, mypy, Python compilation, static Alembic SQL generation, the single migration head, OpenAPI serialization/required-route checks, and the full pytest suite pass. A live PostgreSQL/PostGIS/MinIO migration test and physical-phone HTTPS test require the local Docker daemon or a staging environment; Docker was unavailable during this review.

## Operational activation still required

- Supply `KOK_KINDWISE_API_KEY` through backend secret storage.
- Start Docker (or provide PostgreSQL/PostGIS, Redis, and S3-compatible services), then run `alembic upgrade head`.
- Validate one monitored staging identification and the physical-device HTTPS flow. These checks intentionally cannot be replaced with a live provider call in automated tests.
