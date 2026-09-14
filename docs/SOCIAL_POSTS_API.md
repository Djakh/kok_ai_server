# Social posts API

This document is the mobile integration contract for Instagram-style post timelines in KOK.AI.
All paths are relative to the production API origin:

```text
https://api.kokai.uz/api/v1
```

All post endpoints require `Authorization: Bearer <access_token>`. Responses use the standard
KOK.AI envelope: `success`, `data`, `error`, and `meta`.

## Timelines

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/social/feed?scope=all` | Discovery feed containing all visible posts. |
| `GET` | `/social/feed?scope=following` | Posts from followed authors plus the current user. |
| `GET` | `/social/posts` | Backward-compatible discovery feed. |
| `GET` | `/social/posts/me` | Every non-deleted post owned by the current user. |
| `GET` | `/social/authors/{author_id}/posts` | Every visible post belonging to one author. |
| `GET` | `/social/posts/{post_id}` | One post with viewer-relative state. |

`/social/my-posts` and `/social/author-posts/{author_id}` remain compatibility aliases. New clients
should use `/social/posts/me` and `/social/authors/{author_id}/posts`.

Every timeline accepts:

- `limit`: number of items, clamped to `1..100`; default `20`.
- `cursor`: opaque `next_cursor` from the previous response. Never construct or edit it on-device.

The legacy `/social/posts` route also accepts `user_id` and `near=latitude,longitude,radius_meters`.
Radius must be between 1 meter and 50 kilometers. Prefer the explicit author route for profiles.

Timeline response:

```json
{
  "success": true,
  "data": {
    "items": [],
    "next_cursor": null
  },
  "error": null,
  "meta": {
    "cursor": null,
    "next_cursor": null,
    "limit": 20
  }
}
```

Author and current-user timelines additionally return `data.author` and `data.total_count`. This
means an empty author timeline still has enough information to render its profile header.

Blocked accounts are excluded in both directions. Soft-deleted posts never appear. An unknown or
inactive author returns `404`.

## Post representation

The same post shape is returned by feeds, author timelines, detail, create, and edit:

```json
{
  "id": "c2cd43d3-2a11-46f0-a6c5-e3dc70b7b26e",
  "author_id": "9dab279d-0fd1-4876-9f3b-49d464b7f69c",
  "author": {
    "id": "9dab279d-0fd1-4876-9f3b-49d464b7f69c",
    "username": "djakhh",
    "full_name": "Shokhjakhon",
    "avatar_url": "https://api.kokai.uz/api/v1/media/asset-uuid"
  },
  "content": "A tree worth remembering",
  "image_url": "https://api.kokai.uz/api/v1/media/asset-uuid",
  "image_width": 1080,
  "image_height": 1350,
  "image_aspect_ratio": 0.8,
  "image": {
    "id": "asset-uuid",
    "url": "https://api.kokai.uz/api/v1/media/asset-uuid",
    "width": 1080,
    "height": 1350,
    "aspect_ratio": 0.8,
    "content_type": "image/jpeg"
  },
  "images": [
    {
      "id": "asset-uuid",
      "url": "https://api.kokai.uz/api/v1/media/asset-uuid",
      "width": 1080,
      "height": 1350,
      "aspect_ratio": 0.8,
      "content_type": "image/jpeg"
    }
  ],
  "location": {"latitude": 41.2995, "longitude": 69.2401},
  "created_at": "2026-09-13T12:54:18.070967Z",
  "updated_at": "2026-09-13T12:54:18.070975Z",
  "like_count": 12,
  "comment_count": 3,
  "liked_by_me": true,
  "is_mine": false
}
```

`image_url`, `image`, and the scalar image dimensions are retained for simple and older clients.
`images` is the canonical media collection and currently contains zero or one item. Clients should
already model it as a list so carousel support can be introduced without changing the response.

`liked_by_me` and `is_mine` are calculated for the authenticated viewer and must drive the heart
and owner-action UI. Do not infer ownership from a locally cached username.

## Full-width mobile image layout

The API preserves the uploaded aspect ratio, applies EXIF orientation, validates the decoded image,
and creates an optimized display image capped at approximately two megapixels. The original is kept
privately. Public media is served over the API HTTPS origin rather than exposing MinIO.

For an Instagram-style edge-to-edge Flutter card:

1. Set image width to the available screen/card width.
2. Reserve height as `availableWidth / image.aspect_ratio` before the network image loads.
3. Render with `BoxFit.cover` when intentional edge cropping is desired, or `BoxFit.contain` when
   the complete photograph must remain visible.
4. Do not hard-code pixel height and do not use the source pixel width as logical Flutter pixels.
5. Cache by `image.url`; media responses include cache headers and an ETag.

Example:

```dart
final media = post.image;
final ratio = media?.aspectRatio ?? 1.0;

AspectRatio(
  aspectRatio: ratio,
  child: Image.network(
    media!.url,
    width: double.infinity,
    fit: BoxFit.cover,
  ),
)
```

The server cannot choose a device's logical display size. It supplies a responsive image and exact
dimensions; the full-width behavior is controlled by the mobile widget layout.

## Create a post

The recommended flow is upload first, then create the post.

### 1. Upload

```http
POST /uploads
Content-Type: multipart/form-data
Authorization: Bearer <token>

file=<jpeg-or-png>
purpose=social_post
```

JPEG and PNG are supported, up to 10 MB before processing. Save `data.id` from the response.

### 2. Create

```http
POST /social/posts
Content-Type: application/json
Authorization: Bearer <token>
Idempotency-Key: <new-uuid-for-this-operation>
```

```json
{
  "content": "A tree worth remembering",
  "upload_id": "uploaded-asset-uuid",
  "location": {"latitude": 41.2995, "longitude": 69.2401},
  "created_at": "2026-09-13T12:54:18Z"
}
```

`content` is 1–2000 characters. `location` is optional; when present, it must contain both
coordinates or both values must be `null`. `upload_id` must belong to the authenticated user.
Device paths are rejected. `created_at` must include a timezone. The response is `201` with the
complete post representation.

Multipart creation remains supported for older clients using fields `content`, `created_at`,
optional paired `latitude`/`longitude`, and binary `image`.

## Edit and delete

```http
PATCH /social/posts/{post_id}
```

```json
{"content": "Updated caption", "remove_image": false}
```

At least one real change is required. Only the author can edit. An image can be removed, but cannot
be replaced during edit; create a new post when the media itself must change.

```http
DELETE /social/posts/{post_id}
```

Deletion is soft and author-only. A successful response is `{"deleted": true}` inside the standard
envelope.

## Likes

| Method | Endpoint | Result |
|---|---|---|
| `POST` | `/social/posts/{post_id}/likes` | Like the post. Repeating it is idempotent. |
| `DELETE` | `/social/posts/{post_id}/likes` | Remove the current user's like. Repeating it is idempotent. |
| `GET` | `/social/posts/{post_id}/likes` | List likes with nested user summaries. |

After optimistic UI updates, use the returned post or reload detail to reconcile `liked_by_me` and
`like_count`. The list accepts `cursor` and `limit` and returns `next_cursor`. A missing/deleted post
returns `404`.

## Comments

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/social/posts/{post_id}/comments` | List comments oldest first. |
| `POST` | `/social/posts/{post_id}/comments` | Add a comment. |
| `DELETE` | `/social/posts/{post_id}/comments/{comment_id}` | Delete a comment. |

Create body:

```json
{"content": "Beautiful tree!"}
```

Comment content is 1–500 characters. The list accepts `cursor` and `limit` and returns oldest-first
pages with `next_cursor`. A comment can be deleted by its author or by the owner of the post
containing it. Creating or listing comments for a missing/deleted post returns `404`.

## Recommended mobile screens

- Home: `/social/feed?scope=following`, with a switch to `scope=all` for discovery.
- My profile grid/list: `/social/posts/me`.
- Another profile: `/social/authors/{author_id}/posts`.
- Post detail: `/social/posts/{post_id}` followed by the comments endpoint.
- Infinite scroll: append `items`, request the returned `next_cursor`, and stop when it is `null`.

The API covers the core post lifecycle, author timelines, following/discovery feeds, ownership,
likes, comments, responsive media metadata, blocking, and cursor pagination. Stories, reels, direct
messages, hashtags, mentions, bookmarks, and ranking/recommendation algorithms are separate product
features and are not implied by this posts contract.
