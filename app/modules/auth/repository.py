from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.modules.auth.models import RefreshToken


class RefreshTokenRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, item: RefreshToken) -> RefreshToken:
        self.db.add(item)
        self.db.flush()
        return item

    def by_hash(self, token_hash: str) -> RefreshToken | None:
        return self.db.query(RefreshToken).filter(RefreshToken.token_hash == token_hash).first()

    def revoke(self, item: RefreshToken) -> None:
        item.revoked = True
        item.revoked_at = datetime.now(timezone.utc)
        self.db.add(item)

    def revoke_family(self, family_id) -> None:  # noqa: ANN001
        self.db.query(RefreshToken).filter(RefreshToken.token_family_id == family_id).update(
            {RefreshToken.revoked: True, RefreshToken.revoked_at: datetime.now(timezone.utc)},
            synchronize_session=False,
        )
