from fastapi import Depends
from sqlalchemy.orm import Session

from app.common.db.session import get_db
from app.modules.trees.service import TreeService


def get_tree_service(db: Session = Depends(get_db)) -> TreeService:
    return TreeService(db)
