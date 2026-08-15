from sqlalchemy.orm import Session

from app.modules.achievements.repository import AchievementRepository
from app.modules.social.repository import SocialRepository
from app.modules.trees.models import Tree
from app.modules.users.repository import UserRepository


class ProfileService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.social = SocialRepository(db)
        self.achievements = AchievementRepository(db)

    def stats(self, user_id):
        followers = self.users.follower_count(user_id)
        following = self.users.following_count(user_id)
        posts = len(self.social.list_posts(None, 1000, user_id, None))
        trees = self.db.query(Tree).filter(Tree.owner_user_id == user_id, Tree.deleted_at.is_(None)).count()
        return {
            "followers_count": followers,
            "following_count": following,
            "posts_count": posts,
            "trees_count": trees,
        }
