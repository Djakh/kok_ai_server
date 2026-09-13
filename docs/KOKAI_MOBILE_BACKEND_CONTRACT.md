# KOK.AI mobile/backend integration contract

Status: implemented  
Contract version: 1.3  
Backend API version: 1.3.0  
Verified: 2026-08-21

This is the authoritative contract for the Flutter application. All application paths below are
relative to `/api/v1`. The mobile app calls only this backend; Kindwise credentials and raw Kindwise
responses never belong in the app.

## Runtime and transport

- Production base URL: `--dart-define=API_BASE_URL=https://<host>/api/v1`.
- iOS Simulator: `http://localhost:8000/api/v1`.
- Android Emulator: `http://10.0.2.2:8000/api/v1`.
- Physical device: `http://<development-machine-LAN-IP>:8000/api/v1`.
- Production API and media URLs must use HTTPS.
- Public post, avatar, and tree images are served through `/api/v1/media/{asset_id}`;
  clients must not receive or directly connect to the private S3/MinIO endpoint.
- Coordinates are WGS84 decimal degrees and dates are timezone-aware ISO-8601 UTC.
- Authenticated calls send `Authorization: Bearer <access_token>`.

Success envelope:

```json
{"success":true,"data":{},"error":null,"meta":null}
```

Error envelope:

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "validation_error",
    "message": "Request validation failed",
    "request_id": "uuid",
    "details": {}
  },
  "meta": null
}
```

Collection data uses `{ "items": [], "next_cursor": null }`. Cursors are opaque. Log the response
`X-Request-ID`/`error.request_id`, but never tokens, passwords, image bytes, or precise coordinates.

## Authentication and account lifecycle

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/register` | Create user; returns access and refresh tokens. |
| `POST` | `/auth/login` | Returns access and refresh tokens. |
| `POST` | `/auth/refresh` | Rotates refresh token; atomically persist both returned tokens. |
| `POST` | `/auth/logout` | Revoke supplied refresh token. |
| `GET` | `/auth/me` | Current user. |
| `POST` | `/auth/password-recovery/request` | Non-enumerating reset request by email. |
| `POST` | `/auth/password-recovery/verify` | Verify email and code; returns short-lived reset token. |
| `POST` | `/auth/password-recovery/reset` | Set password using reset token; revokes sessions. |
| `POST` | `/auth/verification/request` | Request `email` or `phone` verification. |
| `POST` | `/auth/verification/resend` | Replace prior verification challenge. |
| `POST` | `/auth/verification/verify` | Confirm channel and code. |
| `POST` | `/auth/change-password` | Current and new password; revokes sessions. |
| `GET` | `/auth/sessions` | Active sessions with `is_current`. |
| `DELETE` | `/auth/sessions/{session_id}` | Revoke one owned session. |
| `DELETE` | `/auth/sessions` | Revoke all sessions. |

Access-token 401 handling must use one serialized refresh. Retry the original call once. A second
401 clears secure storage and returns to login. Never refresh a 403. Password/verification routes
use stable 429 envelopes. In development only, challenge request responses contain `debug_code`
because no email/SMS transport is configured; production never returns it.

### Registration, login, refresh, and token schema

All three token-producing endpoints return a complete pair. `expires_in` is the access-token
lifetime in **seconds** (900 by default); it is not the refresh-token lifetime.

```text
POST /auth/register
request:  {"email":"user@example.com","username":"treefan","password":"Pass1234","full_name":"Tree Fan"}
response: {"access_token":"jwt","refresh_token":"jwt","token_type":"bearer","expires_in":900}

POST /auth/login
request:  {"email":"user@example.com","password":"Pass1234"}
response: {"access_token":"jwt","refresh_token":"jwt","token_type":"bearer","expires_in":900}

POST /auth/refresh
request:  {"refresh_token":"current-refresh-jwt"}
response: {"access_token":"new-jwt","refresh_token":"new-refresh-jwt","token_type":"bearer","expires_in":900}
```

Registration requires a 3–50 character username; `full_name` is nullable/optional. Every successful
refresh rotates the token and **always returns a new refresh token**. Mobile must persist the new
access and refresh tokens together before retrying the original request. Reusing a rotated refresh
token revokes its token family and returns `401 invalid_refresh`.

### Exact recovery, verification, and session bodies

Password recovery is unauthenticated and non-enumerating:

```text
POST /auth/password-recovery/request
request:  {"email":"user@example.com"}
response: {"accepted":true,"expires_in":600,"debug_code":"123456"}

POST /auth/password-recovery/verify
request:  {"email":"user@example.com","code":"123456"}
response: {"verified":true,"reset_token":"opaque-token","expires_at":"ISO-8601 UTC"}

POST /auth/password-recovery/reset
request:  {"reset_token":"opaque-token","new_password":"NewPass123"}
response: {"password_reset":true}
```

`debug_code` exists only outside production and only when the email belongs to a user. Mobile must
not depend on it. Codes are 6 digits, expire after 10 minutes, and allow at most 5 failed attempts.
New passwords are 8–128 characters and must contain at least one letter and one digit. Resetting a
password consumes the reset token and revokes every refresh session.

Email/phone verification is authenticated. Request and resend have the same body and behavior:

```text
POST /auth/verification/request
POST /auth/verification/resend
email body: {"channel":"email"}
phone body: {"channel":"phone","phone_number":"+998901234567"}
response:   {"accepted":true,"channel":"email|phone","expires_in":600,"debug_code":"123456"}

POST /auth/verification/verify
request:  {"channel":"email","code":"123456"}
response: {"verified":true,"channel":"email","verified_at":"ISO-8601 UTC"}

POST /auth/change-password
request:  {"current_password":"OldPass123","new_password":"NewPass123"}
response: {"password_changed":true,"sessions_revoked":true}
```

`phone_number` is required for `channel=phone` and omitted for `channel=email`. Resend invalidates
the previous unconsumed code. Changing a password revokes all refresh sessions, including the
current session; the existing access token may remain usable only until its short expiry.

Session operations do not have request bodies:

```text
GET    /auth/sessions
DELETE /auth/sessions/{session_id}
DELETE /auth/sessions
```

The list response is `{ "items": [...], "next_cursor": null }`. Each session contains `id`,
`created_at`, `expires_at`, nullable `last_rotated_at`, nullable `user_agent`, nullable `ip_address`,
and `is_current`. Deleting one session returns `{ "revoked": true, "session_id": "uuid" }`;
deleting all returns `{ "revoked": true, "all_sessions": true }`. Logout is separate and accepts
`{ "refresh_token": "..." }`.

Account routes:

- `PATCH /users/me/avatar`, `{ "upload_id": "uuid" }`, associates an owned upload.
- `DELETE /users/me/avatar`, removes the association.
- `GET /users/me/export`, returns a versioned personal-data export.
- `POST /users/me/deactivate`, `{ "password": "..." }`, deactivates and revokes sessions.
- `DELETE /users/me`, `{ "password": "..." }`, anonymizes/deactivates and revokes sessions.

### Account lifecycle response schemas

`DELETE /users/me/avatar` returns the complete current-user object with `avatar_url: null`:

```json
{
  "id": "uuid",
  "email": "user@example.com",
  "username": "treefan",
  "full_name": "Tree Fan",
  "role": "user",
  "bio": null,
  "avatar_url": null,
  "created_at": "2026-08-21T10:00:00Z",
  "email_verified_at": null,
  "phone_number": null,
  "phone_verified_at": null
}
```

`GET /users/me/export` returns a synchronous JSON export with a versioned schema:

```json
{
  "exported_at": "2026-08-21T10:00:00Z",
  "schema_version": "1.0",
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "username": "treefan",
    "full_name": "Tree Fan",
    "bio": null,
    "phone_number": null,
    "created_at": "2026-08-20T10:00:00Z"
  },
  "settings": {
    "language_code": "en",
    "privacy_profile_public": true,
    "notifications_enabled": true
  },
  "trees": [{"id":"uuid","name":"School plane","created_at":"ISO-8601 UTC"}],
  "posts": [{"id":"uuid","content":"My tree","created_at":"ISO-8601 UTC"}],
  "comments": [{"id":"uuid","content":"Nice tree","created_at":"ISO-8601 UTC"}],
  "notifications": [{"id":"uuid","title":"Title","body":"Body","created_at":"ISO-8601 UTC"}]
}
```

`POST /users/me/deactivate` returns
`{ "deactivated": true, "sessions_revoked": true }`. `DELETE /users/me` returns
`{ "deleted": true, "sessions_revoked": true }`. Both bodies require the current password, disable
future login immediately, and make subsequent authenticated API calls return `401`.

### Required local-session cleanup

Mobile must clear both locally stored tokens, clear authenticated in-memory state, and navigate to
login immediately after any of these successful operations:

- password change;
- password reset performed on the same device;
- deleting the current session;
- deleting all sessions;
- account deactivation; or
- account deletion.

Deleting a different, non-current session does not log out the current device. Do not wait for the
current access token to expire after a session-ending operation.

## Push devices

```text
POST   /devices
PATCH  /devices/{installation_id}
DELETE /devices/{installation_id}
```

Registration body:

```json
{
  "installation_id": "stable-random-installation-id",
  "push_token": "apns-or-fcm-token",
  "platform": "ios",
  "locale": "en",
  "app_version": "1.0.0",
  "last_seen_at": "2026-08-21T10:00:00Z"
}
```

Platform is `ios` or `android`. Reposting an installation updates it. Responses intentionally expose
only `token_last_four`, never the push token. Delete registration on logout when the installation
should stop receiving user-specific notifications.

`PATCH /devices/{installation_id}` accepts any subset of `push_token`, `locale`, `app_version`,
`enabled`, and `last_seen_at`; it does not accept `platform` or a replacement `installation_id`.
Unknown fields return `422`. `POST` returns HTTP `201`; `PATCH` returns HTTP `200`. Both return:

```json
{
  "installation_id": "stable-random-installation-id",
  "platform": "ios",
  "locale": "en",
  "app_version": "1.0.0",
  "last_seen_at": "2026-08-21T10:00:00Z",
  "enabled": true,
  "token_last_four": "cdef",
  "created_at": "2026-08-21T09:00:00Z",
  "updated_at": "2026-08-21T10:00:00Z"
}
```

Installation ids are globally unique. If another user owns the id, authenticated registration
transfers it only when the submitted push token matches the existing token; this prevents the old
user from continuing to receive pushes on a shared device. A different token returns
`409 installation_owner_conflict`. Patch/delete by a non-owner returns `404 device_not_found`.

On explicit logout, mobile should best-effort call `DELETE /devices/{installation_id}` **before**
revoking the refresh token, while the access token is still valid. A network failure must not block
logout: clear local credentials regardless. Do not unregister on ordinary app close, access-token
refresh, or backgrounding because that would disable push delivery.

## Kindwise-backed tree registration

For the exact capture, retry, provider-mapping, error, and media lifecycle contract, see
[CREATE_TREE_KINDWISE_WORKFLOW.md](CREATE_TREE_KINDWISE_WORKFLOW.md).

Canonical flow:

```text
POST /tree-analyses -> GET /trees/nearby -> POST /trees -> GET /trees/{id}
```

### Analysis

`POST /tree-analyses` is multipart and requires `Idempotency-Key`.

Canonical mobile fields:

- repeated files named `images` (2–5 JPEG/PNG);
- repeated strings named `organs`, aligned by index;
- `latitude`, `longitude`, optional `accuracy_meters`, optional `captured_at`.

The mobile three-photo form uses organs `auto`, `bark`, `leaf`; backend normalizes `auto` to
`whole_tree`. The richer backend form (`photos`, `photo_types`, JSON `location_evidence`) remains
supported. Do not send both naming forms in one request.

Analysis data:

```json
{
  "id": "uuid",
  "provider": "kindwise_plant_id",
  "analyzed_at": "2026-08-21T10:00:00Z",
  "species_candidates": [
    {
      "id": "uuid",
      "scientific_name": "Platanus orientalis",
      "common_name": "Oriental plane",
      "confidence": 0.87,
      "genus": "Platanus",
      "family": "Platanaceae",
      "description": null,
      "representative_image_url": null,
      "image_source_url": null
    }
  ],
  "candidates": [],
  "health": {"status":"not_available","confidence":null,"summary":null},
  "capabilities": {"identification":"available","health":"not_available"},
  "attribution": {"provider":"Kindwise Plant.id","provider_id":"kindwise_plant_id"},
  "uncertainty": {
    "confidence_scale":"0_to_1",
    "candidate_order":"descending_probability",
    "user_confirmation_required":true
  }
}
```

`candidates` is a compatibility alias of `species_candidates`. Health status is
`likely_healthy`, `possible_issue`, or `not_available`; unavailable health is never fabricated.

### Nearby duplicate review

`GET /trees/nearby?latitude=...&longitude=...&radius_meters=25&scientific_name=...`

Radius must be 0–100 meters. Data contains `items`; each item has the stable tree core plus
`distance_meters` and compatibility fields. Nearby matches are suggestions and mobile must require
explicit user review before “create anyway.”

### Tree creation

`POST /trees` is JSON and requires a different `Idempotency-Key`. The canonical mobile species
field is **`confirmed_species`**:

```json
{
  "analysis_id": "uuid",
  "confirmed_species": {
    "id": "candidate-uuid",
    "scientific_name": "Platanus orientalis",
    "common_name": "Oriental plane"
  },
  "latitude": 41.2995,
  "longitude": 69.2401,
  "accuracy_meters": 4.2,
  "captured_at": "2026-08-21T10:00:00Z",
  "nickname": "School plane",
  "notes": "North gate",
  "visibility": "private",
  "duplicate_check_status": "possibleMatches"
}
```

The candidate `id` must belong to the analysis. If a corrected scientific name has no candidate ID,
the backend records it as a manual confirmation. Existing fields `selected_candidate_id`,
`manual_scientific_name`, and full `location_evidence` remain backward compatible.

`duplicate_check_status` is exactly one of:

- `noNearbyTrees` — no candidates were returned; this is the default when omitted.
- `possibleMatches` — candidates were shown and the user explicitly chose to create anyway.
- `skippedDueToNetworkFailure` — duplicate lookup could not complete and the user continued.

`visibility` is exactly `private` or `public`; the default is `private`. For
`confirmed_species`, `scientific_name` is required, `common_name` is nullable, and `id` and
`candidate_id` are equivalent candidate-id aliases. If both aliases are supplied, they must match.
Unknown keys inside `confirmed_species` are **rejected** with HTTP `422`; they are not ignored. When
a candidate id is supplied, the server's stored candidate is authoritative over client label text.

### Tree editing

`PATCH /trees/{tree_id}` exists and is owner-only. Its JSON body accepts any non-empty subset of:

```json
{
  "nickname": "School plane — north gate",
  "notes": "Watered on Friday",
  "visibility": "public",
  "confirmed_species": {
    "scientific_name": "Platanus orientalis",
    "common_name": "Oriental plane"
  }
}
```

- `nickname`: non-null string, 1–120 characters. Deprecated `name` is temporarily accepted as an
  alias, but mobile must send `nickname`; sending both returns `422`.
- `notes`: string up to 2000 characters or `null` to clear it.
- `visibility`: non-null `private` or `public`.
- `confirmed_species`: the same strict object used during creation. A candidate id must belong to
  this tree's original analysis; without an id it is recorded as a manual correction.

Unknown fields return `422`. User-controlled `status` is not supported; verification status is
moderator-owned. Location is not editable through this route because a new coordinate requires GPS
evidence and moderation. Report an incorrect location through `/trees/{tree_id}/issues`. Success
returns the complete stable tree detail object.

### Follow-up scan

`POST /trees/{tree_id}/scans` accepts the same multipart aliases and coordinates plus required
`Idempotency-Key`, optional `captured_at` and `notes`. `GET /trees/{tree_id}/scans` returns `items`.
Scan data includes health capability, attribution, uncertainty, provider, and warnings.

## Stable tree core and map

List, map, nearby, create, and detail items include:

```json
{
  "id": "uuid",
  "nickname": "School plane",
  "confirmed_species": {
    "scientific_name": "Platanus orientalis",
    "common_name": "Oriental plane"
  },
  "location": {
    "latitude": 41.2995,
    "longitude": 69.2401,
    "accuracy_meters": 4.2
  },
  "latest_health": {"status":"not_available"},
  "primary_image_url": "https://cdn.example.com/...",
  "notes": "",
  "created_at": "2026-08-21T10:00:00Z",
  "updated_at": "2026-08-21T10:00:00Z"
}
```

`GET /trees` returns all public trees plus the authenticated user's private trees. Filters are
`cursor`, `limit` (1–200), `status` (`pending|verified|rejected`), `owner_id`, `q`, `species`, and
`sort` (`newest|nearest|last_scanned`). Nearest requires latitude/longitude.

Canonical map query is `bbox=west,south,east,north`. Named `south`, `west`, `north`, `east` are
accepted as a compatibility alias; unknown query parameters are ignored. Bounds must be valid and
area must not exceed four square degrees. Center/radius mode is also accepted up to 50 km. Map data:

```json
{"items":[],"clusters":[],"mode":"markers","next_cursor":null}
```

The current contract returns every displayable marker inside an accepted viewport, so server-side
clusters are not required. Records without a valid stored location cannot enter the spatial query.

## Social ownership contract

Posts contain `id`, nested `author` (`id`, `username`, `full_name`, `avatar_url`), `content`,
`created_at`, `updated_at`, `like_count`, `comment_count`, `liked_by_me`, and `is_mine`, plus nullable
image/location. Comments contain the same author/timestamp/viewer fields and `post_id`. Server-side
authorization remains authoritative.

```text
GET/POST    /social/posts
GET         /social/feed?scope=all|following
GET         /social/posts/me
GET         /social/authors/{author_id}/posts
GET/PATCH/DELETE /social/posts/{post_id}
GET/POST/DELETE  /social/posts/{post_id}/likes
GET/POST    /social/posts/{post_id}/comments
DELETE      /social/posts/{post_id}/comments/{comment_id}
```

See [SOCIAL_POSTS_API.md](SOCIAL_POSTS_API.md) for the complete timeline, media-layout, pagination,
ownership, likes, and comments integration guide.

Posts can associate an upload using `upload_id`; local device paths are rejected. Feeds exclude
users blocked in either direction.

### Exact social request and detail schemas

Canonical JSON post creation is:

```json
{
  "content": "My newly registered tree",
  "upload_id": "optional-upload-uuid",
  "location": {"latitude": 41.2995, "longitude": 69.2401},
  "created_at": "2026-08-21T10:00:00Z"
}
```

`content` is 1–2000 characters. `upload_id` is nullable/optional and must identify an owned upload.
`location` is required for compatibility: send both numeric coordinates, or send
`{ "latitude": null, "longitude": null }` for no location. Supplying only one coordinate returns
`422`. `created_at` is a timezone-aware ISO-8601 timestamp. Deprecated `image_path` accepts only an
upload UUID alias; local filesystem paths are rejected. Multipart creation remains supported with
`content`, `created_at`, optional paired `latitude`/`longitude`, and optional binary `image`.

Post editing accepts `content` and/or image removal:

```json
{"content":"Updated caption","remove_image":true}
```

`content` remains 1–2000 characters. `remove_image=true` detaches the existing image and is
idempotent if no image exists. `remove_image=false` by itself is not a valid change. Adding or
replacing a post image after creation is not supported. Comment creation is exactly
`{ "content": "Nice tree" }`, with 1–500 characters. Unknown request fields return `422`.

`GET /social/posts/{post_id}`, successful create, and successful patch return the same data shape:

```json
{
  "id": "uuid",
  "author_id": "uuid",
  "author": {
    "id": "uuid",
    "username": "treefan",
    "full_name": "Tree Fan",
    "avatar_url": "https://cdn.example.com/avatar.jpg"
  },
  "content": "My newly registered tree",
  "image_url": "https://cdn.example.com/post.jpg",
  "image_width": 1080,
  "image_height": 1350,
  "image_aspect_ratio": 0.8,
  "image": {"url":"https://cdn.example.com/post.jpg","width":1080,"height":1350,"aspect_ratio":0.8},
  "images": [{"url":"https://cdn.example.com/post.jpg","width":1080,"height":1350,"aspect_ratio":0.8}],
  "location": {"latitude": 41.2995, "longitude": 69.2401},
  "created_at": "2026-08-21T10:00:00Z",
  "updated_at": "2026-08-21T10:00:00Z",
  "like_count": 3,
  "comment_count": 1,
  "liked_by_me": true,
  "is_mine": true
}
```

`image_url`, author `full_name`/`avatar_url`, and both location values may be null. Viewer-relative
fields are calculated for the authenticated caller. Missing/deleted posts return `404`.

## Reporting, blocking, and tree issues

```text
POST   /reports
POST   /users/{user_id}/block
DELETE /users/{user_id}/block
GET    /users/me/blocked
POST   /trees/{tree_id}/issues
GET    /trees/issues/mine
```

Report target type is `user`, `post`, `comment`, or `tree`. Stable reasons are `spam`, `harassment`,
`hate`, `misinformation`, `unsafe_content`, `privacy`, and `other`.

Tree issue categories are `damage`, `disease`, `hazard`, `incorrect_location`,
`incorrect_species`, and `other`. Issue bodies accept notes, up to five owned `upload_ids`, and an
optional paired latitude/longitude. Status initially equals `submitted`.

Exact issue creation example:

```json
{
  "category": "damage",
  "notes": "Large broken branch over the footpath",
  "upload_ids": ["owned-upload-uuid"],
  "latitude": 41.2995,
  "longitude": 69.2401
}
```

`notes` is nullable and limited to 2000 characters; `upload_ids` defaults to `[]` and allows at most
five owned assets. Latitude and longitude must both be supplied or both omitted. Create returns HTTP
`201`; every created/listed issue item is:

```json
{
  "id": "uuid",
  "tree_id": "uuid",
  "category": "damage",
  "notes": "Large broken branch over the footpath",
  "upload_ids": ["owned-upload-uuid"],
  "location": {"latitude": 41.2995, "longitude": 69.2401},
  "status": "submitted",
  "created_at": "2026-08-21T10:00:00Z",
  "updated_at": "2026-08-21T10:00:00Z"
}
```

`location` is null when coordinates were omitted. `GET /trees/issues/mine` returns
`{ "items": [issue...], "next_cursor": null }`. The stable status enum is `submitted`,
`under_review`, `resolved`, or `rejected`. This API creates `submitted`; later values are written by
the moderation workflow and are read-only for mobile.

The exact generic report body is:

```json
{
  "target_type": "post",
  "target_id": "uuid",
  "reason": "spam",
  "details": "optional text, maximum 2000 characters"
}
```

The target must exist, and a user cannot report themselves. Success returns HTTP `201` with `id`,
`target_type`, `target_id`, `reason`, `status` (`submitted`), `created_at`, and `updated_at`.

## Profile settings and localization schemas

`GET /profile/settings` and a successful `PATCH /profile/settings` return exactly:

```json
{
  "language_code": "en",
  "privacy_profile_public": true,
  "notifications_enabled": true
}
```

The settings patch body accepts either or both optional boolean fields:

```json
{"privacy_profile_public":false,"notifications_enabled":true}
```

It does not change language and rejects unknown fields with HTTP `422`. Language uses the separate
`GET/PATCH /profile/localization` API. Its patch body is `{ "language_code": "en|ru|uz" }`; its
response has the same three-field settings shape. `GET /languages` returns those supported codes as
`{ "items": [{"code":"en"},{"code":"ru"},{"code":"uz"}], "next_cursor": null }`.

## Upload schemas and purposes

`POST /uploads` uses `multipart/form-data` with required binary `file` and optional `purpose`.
`POST /uploads/batch` uses 1–5 repeated binary fields named `files` and one optional shared
`purpose`. Purpose defaults to `general` and is exactly one of `general`, `avatar`, `social_post`, or
`tree_issue`. Purpose is classification metadata; attaching the returned upload id through the
avatar, post, or issue API remains authoritative.

Only JPEG (`image/jpeg`) and PNG (`image/png`) images are accepted. Each source file is limited to
10 MiB and 40 million decoded pixels. Unsupported content returns `415`; excess size returns `413`.
The single-upload response data and every batch item contain:

```json
{
  "id": "uuid",
  "url": "https://cdn.example.com/...",
  "content_type": "image/jpeg",
  "file_name": "photo.jpg",
  "file_size": 123456,
  "width": 1920,
  "height": 1080,
  "purpose": "avatar",
  "status": "available",
  "attached_at": null,
  "expires_at": "ISO-8601 UTC",
  "created_at": "ISO-8601 UTC",
  "updated_at": "ISO-8601 UTC"
}
```

Batch response data is `{ "items": [...], "next_cursor": null }`. Unattached uploads begin with
`status=available` and expire after the configured abandoned-upload TTL (24 hours by default).
Association changes status to `attached`, sets `attached_at`, and clears `expires_at`.

## Remaining connected APIs

```text
GET/PATCH /users/me
GET       /users/{id}
GET       /users/{id}/followers
GET       /users/{id}/following
POST/DELETE /users/{id}/follow
GET       /profile/stats
GET       /profile/achievements
GET       /profile/posts
GET       /profile/liked-posts
GET/PATCH /profile/settings
GET/PATCH /profile/localization
GET       /languages
POST      /uploads
POST      /uploads/batch
GET       /uploads/{id}
GET       /notifications
PATCH     /notifications/{id}/read
POST      /notifications/read-all
GET       /version
```

Profile stats use `tree_count`, `post_count`, `follower_count`, and `following_count`. Plural legacy
counter aliases remain temporarily. Upload associations change an asset from abandoned to attached,
preventing cleanup. Notification lists use collection data.

## Mobile version response

Canonical request: `GET /version?platform=ios&current_version=1.0.0`. Exact response data:

```json
{
  "version": "1.3.0",
  "minimum_supported_version": "1.0.0",
  "latest_version": "1.1.0",
  "force_upgrade": false,
  "platform": "ios",
  "store_url": "https://apps.apple.com/app/id000000000",
  "store_urls": {
    "ios": "https://apps.apple.com/app/id000000000",
    "android": "https://play.google.com/store/apps/details?id=example"
  },
  "maintenance": {
    "active": false,
    "message": null
  },
  "maintenance_status": "operational",
  "message": null,
  "provider": "kindwise_plant_id"
}
```

`version` is the backend API release. Mobile compatibility uses `minimum_supported_version` and
`latest_version`. `store_url` is the URL selected for the requested platform; `store_urls.ios` and
`store_urls.android` always contain the two configured values. Every store URL is nullable.
`maintenance_status` is exactly `operational` or `active`. Both top-level `message` and
`maintenance.message` are nullable strings and currently contain the same configured message.

Versions use exactly three non-negative numeric components (`major.minor.patch`), for example
`1.4.2`. An invalid `current_version` or platform returns the normal validation envelope with HTTP
`422`. If `current_version` is omitted, the request succeeds but `force_upgrade=false` because no
comparison is possible. If `platform` is omitted, `platform` and `store_url` are null while the
complete `store_urls` object remains available. `force_upgrade=true` only when the supplied current
version is lower than `minimum_supported_version`; being below `latest_version` alone does not force
an upgrade.

## Idempotency and retries

- Persist a draft and deterministic key before analysis/create/scan requests.
- Retry an uncertain mutation only with the same key and identical semantic content.
- The same key with different content returns `idempotency_conflict`.
- Honor `Retry-After` and `error.details.retry_after_seconds` on 429.
- Preserve drafts on 429/5xx/timeout; do not invent a successful provider result.

## Explicitly not implemented

Leaderboard, challenges, coins, streaks, and environmental-impact calculations remain disabled.
The supplied mobile requirements contain no approved formulas, calculation versions, reward rules,
or product decision confirming these features. They must not be implemented from guesses.
