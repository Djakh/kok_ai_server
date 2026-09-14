from functools import lru_cache

from fastapi import Depends
from sqlalchemy.orm import Session

from app.common.config import get_settings
from app.common.db.session import get_db
from app.modules.tree_analyses.kindwise import KindwisePlantIdClient
from app.modules.tree_analyses.openai_provider import OpenAIPlantAnalysisProvider
from app.modules.tree_analyses.provider import PlantAnalysisProvider
from app.modules.tree_analyses.service import TreeAnalysisService


@lru_cache
def get_plant_analysis_provider() -> PlantAnalysisProvider:
    settings = get_settings()
    if settings.plant_analysis_provider == "openai":
        return OpenAIPlantAnalysisProvider(settings)
    return KindwisePlantIdClient(settings)


def get_tree_analysis_service(
    db: Session = Depends(get_db),
    provider: PlantAnalysisProvider = Depends(get_plant_analysis_provider),
) -> TreeAnalysisService:
    return TreeAnalysisService(db, provider, get_settings())
