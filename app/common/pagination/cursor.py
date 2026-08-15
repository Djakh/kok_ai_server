import base64
import binascii
import uuid
from datetime import datetime

from app.common.errors.exceptions import AppError


def encode_cursor(created_at: datetime, item_id: str) -> str:
    raw = f"{created_at.isoformat()}|{item_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("utf-8")



def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.b64decode(cursor.encode("utf-8"), altchars=b"-_", validate=True).decode(
            "utf-8"
        )
        created_at_raw, item_id = raw.split("|", 1)
        created_at = datetime.fromisoformat(created_at_raw)
        if created_at.tzinfo is None:
            raise ValueError("cursor timestamp must include a timezone")
        uuid.UUID(item_id)
        return created_at, item_id
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise AppError("INVALID_CURSOR", "The pagination cursor is invalid.", 422) from exc
