import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.common.db.session import get_db
from app.common.security.jwt import TokenKind, decode_token
from app.modules.users.models import User

bearer_scheme = HTTPBearer(auto_error=True)


class CurrentUser:
    def __init__(self, user: User, session_id: str | None = None):
        self.user = user
        self.session_id = session_id


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    try:
        payload = decode_token(credentials.credentials, TokenKind.ACCESS)
        user_id = uuid.UUID(payload["sub"])
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc

    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    request.state.principal_id = str(user.id)
    return CurrentUser(user=user, session_id=payload.get("sid"))


def require_roles(roles: set[str]):
    def checker(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        role_value = (
            current.user.role.value
            if hasattr(current.user.role, "value")
            else str(current.user.role)
        )
        if role_value not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return current

    return checker
