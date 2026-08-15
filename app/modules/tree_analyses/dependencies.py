from fastapi import Depends
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.common.db.session import get_db
from app.modules.tree_analyses.kindwise import KindwisePlantIdClient
from app.modules.tree_analyses.service import TreeAnalysisService


def get_tree_analysis_service(db: Session = Depends(get_db)) -> TreeAnalysisService:
    settings = get_settings()
    return TreeAnalysisService(db, KindwisePlantIdClient(settings), settings)
