from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def success_response(data: Any, meta: dict[str, Any] | None = None, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder({"success": True, "data": data, "error": None, "meta": meta}),
    )



def error_response(
    code: str,
    message: str,
    details: Any = None,
    status_code: int = 400,
    request_id: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            {
            "success": False,
            "data": None,
            "error": {
                "code": code.lower(),
                "message": message,
                "request_id": request_id,
                "details": details or {},
            },
            "meta": None,
            }
        ),
    )
