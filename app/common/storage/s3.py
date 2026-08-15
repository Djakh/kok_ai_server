import hashlib
import io
import uuid
from datetime import datetime, timezone

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from PIL import Image
from starlette.datastructures import UploadFile

from app.common.config import get_settings
from app.common.errors.exceptions import AppError

settings = get_settings()



def get_s3_client() -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        use_ssl=settings.s3_use_ssl,
        config=Config(
            connect_timeout=5,
            read_timeout=20,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )



def ensure_bucket() -> None:
    client = get_s3_client()
    buckets = client.list_buckets().get("Buckets", [])
    names = {b["Name"] for b in buckets}
    if settings.s3_bucket not in names:
        client.create_bucket(Bucket=settings.s3_bucket)



def _validate_upload(file: UploadFile) -> None:
    if file.content_type not in settings.allowed_image_types_list:
        raise AppError("unsupported_media_type", "Unsupported image format", 415)



def upload_image(file: UploadFile, owner_id: str) -> dict[str, str | int]:
    _validate_upload(file)
    content = file.file.read()
    size = len(content)
    if size > settings.max_image_size_bytes:
        raise AppError("file_too_large", "Image exceeds max size", 413)

    from app.modules.tree_analyses.images import _prepare_one

    prepared = _prepare_one(content, file.filename or "image", settings)
    with Image.open(io.BytesIO(prepared.content)) as decoded:
        width, height = decoded.size
    prefix = (
        f"uploads/{owner_id}/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{uuid.uuid4()}"
    )
    original_key = f"{prefix}/original.{prepared.extension}"
    key = f"{prefix}/display.{prepared.extension}"
    client = get_s3_client()
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=original_key,
        Body=prepared.original_content,
        ContentType=prepared.content_type,
    )
    client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=prepared.content,
        ContentType=prepared.content_type,
    )
    public_url = f"{settings.s3_public_base_url}/{settings.s3_bucket}/{key}"
    return {
        "key": key,
        "original_key": original_key,
        "url": public_url,
        "file_size": size,
        "sha256": hashlib.sha256(content).hexdigest(),
        "content_type": prepared.content_type,
        "width": width,
        "height": height,
    }


def put_private_image(
    content: bytes,
    owner_id: str,
    content_type: str,
    extension: str,
) -> str:
    """Persist a normalized analysis image and return only its internal object key."""
    key = (
        f"tree-analyses/{owner_id}/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/"
        f"{uuid.uuid4()}.{extension}"
    )
    get_s3_client().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=content,
        ContentType=content_type,
    )
    return key


def get_private_image_url(object_key: str, expires_seconds: int = 900) -> str:
    """Create a short-lived URL; callers must authorize access before invoking this."""
    return str(
        get_s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket, "Key": object_key},
            ExpiresIn=expires_seconds,
        )
    )
