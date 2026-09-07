"""Canonical model registry, shared by runtime sessions and Alembic.

Add every mapped model here. Model modules must import Base from db.base and
must not import sessions or this registry (which would create import cycles).
The registry completeness test discovers model files independently, so a new
model omitted here fails CI even if no existing foreign key points to it yet.
"""
from app.common.db.outbox import OutboxEvent
from app.modules.achievements.models import Achievement, UserAchievement
from app.modules.auth.models import RefreshToken, VerificationChallenge
from app.modules.mobile_support.models import (
    ContentReport,
    DeviceInstallation,
    TreeIssue,
    UserBlock,
)
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
    "ContentReport",
    "DeviceInstallation",
    "OutboxEvent",
    "RefreshToken",
    "VerificationChallenge",
    "SocialPost",
    "SocialPostComment",
    "SocialPostImage",
    "SocialPostLike",
    "Tree",
    "TreeIssue",
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
    "UserBlock",
    "UserAchievement",
    "UserSettings",
]
