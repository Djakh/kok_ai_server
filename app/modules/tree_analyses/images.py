from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

from app.common.config import Settings
from app.common.errors.exceptions import AppError

PHOTO_TYPES = {"whole_tree", "leaf", "bark", "flower_or_fruit", "additional"}
JPEG_SIGNATURE = b"\xff\xd8\xff"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class PreparedImage:
    original_content: bytes
    content: bytes
    content_type: str
    extension: str
    checksum: str
    original_filename: str


def validate_photo_types(photo_types: list[str], image_count: int) -> list[str]:
    normalized = [value.strip().lower() for value in photo_types]
    if len(normalized) != image_count:
        raise AppError("validation_error", "photos and photo_types must have equal counts.", 422)
    if any(value not in PHOTO_TYPES for value in normalized):
        raise AppError("validation_error", "An unsupported photo_type was supplied.", 422)
    if normalized.count("whole_tree") != 1 or normalized.count("leaf") != 1:
        raise AppError("validation_error", "Exactly one whole_tree and one leaf photo are required.", 422)
    if any(normalized.count(value) > 1 for value in PHOTO_TYPES):
        raise AppError("validation_error", "Each optional photo type may appear at most once.", 422)
    return normalized


async def prepare_images(
    files: list[UploadFile], settings: Settings, minimum: int = 1
) -> list[PreparedImage]:
    if not minimum <= len(files) <= settings.ai_max_images:
        raise AppError(
            "INVALID_IMAGE_COUNT",
            f"Upload between {minimum} and {settings.ai_max_images} images.",
            422,
        )

    prepared: list[PreparedImage] = []
    original_total = 0
    normalized_total = 0
    for upload in files:
        content = await upload.read(settings.ai_max_image_bytes + 1)
        if len(content) > settings.ai_max_image_bytes:
            raise AppError("UPLOAD_TOO_LARGE", "An uploaded image exceeds the size limit.", 413)
        original_total += len(content)
        if original_total > settings.ai_max_request_bytes:
            raise AppError("UPLOAD_TOO_LARGE", "The combined image upload exceeds the size limit.", 413)
        normalized = _prepare_one(content, upload.filename or "image", settings)
        normalized_total += len(normalized.content)
        if normalized_total > settings.ai_max_request_bytes:
            raise AppError("UPLOAD_TOO_LARGE", "The normalized images exceed the size limit.", 413)
        prepared.append(normalized)
    return prepared


def _prepare_one(content: bytes, filename: str, settings: Settings) -> PreparedImage:
    if content.startswith(JPEG_SIGNATURE):
        expected_format, mime, extension = "JPEG", "image/jpeg", "jpg"
        if not content.endswith(b"\xff\xd9"):
            raise AppError("INVALID_IMAGE", "JPEG contains trailing or incomplete data.", 415)
    elif content.startswith(PNG_SIGNATURE):
        expected_format, mime, extension = "PNG", "image/png", "png"
        if not content.endswith(b"IEND\xaeB`\x82"):
            raise AppError("INVALID_IMAGE", "PNG contains trailing or incomplete data.", 415)
    else:
        raise AppError(
            "INVALID_IMAGE",
            "The uploaded file is not a supported JPEG or PNG image.",
            415,
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as probe:
                probe.verify()
            with Image.open(io.BytesIO(content)) as source:
                if source.format != expected_format:
                    raise AppError("INVALID_IMAGE", "Image signature and decoded format disagree.", 415)
                if getattr(source, "is_animated", False):
                    raise AppError("INVALID_IMAGE", "Animated images are not supported.", 415)
                width, height = source.size
                if width <= 0 or height <= 0 or width * height > settings.ai_max_pixels:
                    raise AppError("INVALID_IMAGE_DIMENSIONS", "Image dimensions are not allowed.", 422)
                original_normalized = ImageOps.exif_transpose(source).copy()
                normalized = original_normalized.copy()
                if width * height > 2_000_000:
                    scale = (2_000_000 / (width * height)) ** 0.5
                    normalized = normalized.resize(
                        (max(1, int(width * scale)), max(1, int(height * scale))),
                        Image.Resampling.LANCZOS,
                    )
                original_output = io.BytesIO()
                output = io.BytesIO()
                if expected_format == "JPEG":
                    original_normalized.convert("RGB").save(
                        original_output, format="JPEG", quality=94, optimize=True
                    )
                    normalized.convert("RGB").save(output, format="JPEG", quality=90, optimize=True)
                else:
                    if original_normalized.mode not in {"RGB", "RGBA", "L", "LA", "P"}:
                        original_normalized = original_normalized.convert("RGBA")
                    if normalized.mode not in {"RGB", "RGBA", "L", "LA", "P"}:
                        normalized = normalized.convert("RGBA")
                    original_normalized.save(original_output, format="PNG", optimize=True)
                    normalized.save(output, format="PNG", optimize=True)
    except AppError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise AppError("IMAGE_DECODE_FAILED", "The uploaded image could not be decoded safely.", 422) from exc
    except Image.DecompressionBombWarning as exc:
        raise AppError("INVALID_IMAGE_DIMENSIONS", "Image dimensions are not allowed.", 422) from exc

    normalized_content = output.getvalue()
    original_normalized_content = original_output.getvalue()
    if len(normalized_content) > settings.ai_max_image_bytes or len(
        original_normalized_content
    ) > settings.ai_max_image_bytes:
        raise AppError("UPLOAD_TOO_LARGE", "A normalized image exceeds the size limit.", 413)
    return PreparedImage(
        original_content=original_normalized_content,
        content=normalized_content,
        content_type=mime,
        extension=extension,
        checksum=hashlib.sha256(normalized_content).hexdigest(),
        original_filename=filename,
    )
