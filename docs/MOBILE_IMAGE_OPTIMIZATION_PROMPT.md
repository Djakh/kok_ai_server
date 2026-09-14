# Prompt: Implement Mobile Image Optimization

Copy the prompt below into the KOK.AI Flutter repository task.

---

Implement production-quality image optimization for every KOK.AI Flutter image upload, especially
tree analysis and social-post uploads. Inspect the existing architecture and reuse its API client,
state management, error model, logging, and test conventions. Do not introduce a second networking
stack.

## Backend contract

- Accepted formats are JPEG and PNG.
- Backend hard limit is 15 MiB (15,728,640 bytes) per source image.
- Tree-analysis hard limit is 40,000,000 source-image bytes combined, excluding normal multipart
  framing.
- Tree analysis accepts 2–5 files. File and organ/category arrays must remain aligned by index.
- A 413 HTML response means the reverse proxy rejected the body. A KOK.AI JSON 413 with
  `error.code=upload_too_large` means the backend rejected it.
- Never send image bytes as base64 inside JSON. Use multipart binary files.

These are safety ceilings, not upload targets. Mobile should produce much smaller requests.

## Required optimization behavior

Create one reusable image-optimization service used by camera and gallery flows before multipart
construction.

For ordinary camera/gallery photographs:

1. Read and correct EXIF orientation.
2. Resize proportionally so the longest edge is at most 2048 pixels. Never upscale.
3. Encode as JPEG at quality 82, using a `.jpg` filename and `image/jpeg` MIME type.
4. Remove unnecessary metadata where supported, but do not alter the visible orientation.
5. Target at most 3 MiB per optimized file and 10 MiB combined for a normal three-photo tree
   analysis.
6. If a file remains above 3 MiB, retry from the orientation-corrected source at qualities 74 and
   66. If still too large, resize the longest edge to 1600 pixels and encode at quality 72.
7. If the final result is still above 8 MiB, stop before networking and show a localized message
   asking the user to retake/select a smaller image. Never attempt a request above the backend hard
   limits.

For PNG files that require transparency, preserve PNG and resize to a maximum 2048-pixel longest
edge. Ordinary photos should become JPEG. Do not convert transparent artwork to a black-backed
JPEG.

Run decoding, resizing, and encoding outside the UI thread using the project's established isolate
or background-work mechanism. Show preparation/upload progress, support cancellation, and clean up
temporary optimized files after success, cancellation, or terminal failure. Do not overwrite the
user's original camera/gallery file.

## Request and retry rules

- Construct multipart requests from the optimized temporary files.
- Calculate actual byte lengths after encoding, before starting the request.
- Validate every file is no more than 15,728,640 bytes and the tree-analysis total is below
  40,000,000 bytes.
- Preserve file ordering so `images[i]` still matches `organs[i]` (or `photos[i]` matches
  `photo_types[i]`).
- Generate the idempotency key after optimization. For an unchanged network retry, reuse the same
  optimized bytes and the same idempotency key.
- If photos are reselected, recaptured, or re-encoded into different bytes, start a new logical
  request with a new idempotency key.
- Do not automatically retry validation errors. Retry transient network/5xx errors with the
  project's bounded exponential-backoff policy.

## Logging and privacy

In debug logs record only:

- original width, height, and byte count;
- optimized width, height, byte count, format, and quality;
- combined multipart image-byte count;
- elapsed optimization time and request ID.

Do not log image bytes, base64, authorization headers, local private paths in production, or full
signed media URLs.

## User experience

- Start optimization immediately after capture/selection and display a non-blocking “Preparing
  photos” state.
- Keep the existing preview and category/organ selection UI.
- If optimization fails, identify which photo failed and let the user replace only that photo.
- For 413, show “Photos are too large to upload. Please choose smaller photos or try again.” Do not
  display raw Nginx HTML or Dio's generic status-code explanation.

## Tests and acceptance criteria

Add unit/widget tests proving:

- a 1440×2560 JPEG is orientation-correct, reduced to a maximum 2048-pixel longest edge, and is
  sent as `image/jpeg`;
- an already-small JPEG is never upscaled;
- transparent PNG remains transparent PNG;
- iterative quality/resizing enforces the target and hard byte limits;
- three optimized tree photos remain aligned with their organ values;
- retries reuse identical optimized bytes and the same idempotency key;
- changed bytes use a new idempotency key;
- HTML and JSON 413 responses map to the same friendly domain error;
- temporary files are removed on success, cancellation, and failure.

Return a concise implementation summary, list the changed files, and report formatter, analyzer,
and test results. Do not claim success unless the tests pass.

---
