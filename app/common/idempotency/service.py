import hashlib
import json
from typing import Any

from fastapi import Request, UploadFile

from app.common.cache.redis_client import redis_client
from app.common.errors.exceptions import AppError

IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


async def get_body_hash(request: Request) -> str:
    body = await request.body()
    return hashlib.sha256(body).hexdigest()


def get_bytes_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


async def get_multipart_hash(form: dict[str, Any]) -> str:
    normalized: dict[str, Any] = {}
    for key, value in form.items():
        if isinstance(value, UploadFile):
            file_bytes = await value.read()
            normalized[key] = {
                "filename": value.filename,
                "content_type": value.content_type,
                "sha256": hashlib.sha256(file_bytes).hexdigest(),
            }
            await value.seek(0)
        else:
            normalized[key] = value
    return get_bytes_hash(json.dumps(normalized, sort_keys=True, default=str).encode("utf-8"))


def _response_key(user_id: str, idempotency_key: str) -> str:
    return f"idem:resp:{user_id}:{idempotency_key}"


def _hash_key(user_id: str, idempotency_key: str) -> str:
    return f"idem:hash:{user_id}:{idempotency_key}"


def get_replayed_response(user_id: str, idempotency_key: str, body_hash: str) -> dict[str, Any] | None:
    existing_hash: Any = redis_client.get(_hash_key(user_id, idempotency_key))
    if existing_hash and existing_hash != body_hash:
        raise AppError("idempotency_conflict", "Idempotency-Key already used with different payload", 409)
    raw: Any = redis_client.get(_response_key(user_id, idempotency_key))
    if raw:
        return json.loads(raw)
    return None


def save_response(user_id: str, idempotency_key: str, body_hash: str, response_payload: dict[str, Any]) -> None:
    redis_client.setex(_hash_key(user_id, idempotency_key), IDEMPOTENCY_TTL_SECONDS, body_hash)
    redis_client.setex(
        _response_key(user_id, idempotency_key),
        IDEMPOTENCY_TTL_SECONDS,
        json.dumps(response_payload, default=str),
    )
