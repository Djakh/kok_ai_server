# Import all models so Alembic can discover metadata
from app.common.db.outbox import OutboxEvent
from app.modules.achievements.models import Achievement, UserAchievement
from app.modules.auth.models import RefreshToken
from app.modules.notifications.models import Notification
from app.modules.social.models import SocialPost, SocialPostComment, SocialPostImage, SocialPostLike
from app.modules.tree_analyses.models import (
    IdempotencyRecord,
    TreeAnalysis,
    TreeAnalysisCandidate,
    TreeAnalysisImage,
    TreeScan,
)
from app.modules.trees.models import Tree, TreeEvent, TreeImage, TreeLocation
from app.modules.uploads.models import UploadedAsset
from app.modules.users.models import AuditLog, Follow, User, UserSettings

__all__ = [
    "Achievement",
    "AuditLog",
    "Follow",
    "Notification",
    "OutboxEvent",
    "RefreshToken",
    "SocialPost",
    "SocialPostComment",
    "SocialPostImage",
    "SocialPostLike",
    "Tree",
    "TreeAnalysis",
    "TreeAnalysisCandidate",
    "TreeAnalysisImage",
    "IdempotencyRecord",
    "TreeEvent",
    "TreeImage",
    "TreeLocation",
    "TreeScan",
    "UploadedAsset",
    "User",
    "UserAchievement",
    "UserSettings",
]
