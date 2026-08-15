from fastapi import APIRouter

from app.modules.auth.router import router as auth_router
from app.modules.notifications.router import router as notifications_router
from app.modules.profile.router import localization_router
from app.modules.profile.router import router as profile_router
from app.modules.social.router import router as social_router
from app.modules.tree_analyses.router import router as tree_analyses_router
from app.modules.trees.router import router as trees_router
from app.modules.uploads.router import router as uploads_router
from app.modules.users.router import router as users_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(profile_router)
api_router.include_router(localization_router)
api_router.include_router(uploads_router)
api_router.include_router(tree_analyses_router)
api_router.include_router(trees_router)
api_router.include_router(social_router)
api_router.include_router(notifications_router)
