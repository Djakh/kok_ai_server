from datetime import datetime, timezone

from geoalchemy2 import WKTElement

from app.common.db.session import SessionLocal
from app.common.security.password import hash_password
from app.modules.achievements.models import Achievement, UserAchievement
from app.modules.notifications.models import Notification
from app.modules.social.models import SocialPost, SocialPostComment, SocialPostImage, SocialPostLike
from app.modules.trees.models import (
    Tree,
    TreeEvent,
    TreeEventType,
    TreeImage,
    TreeImageKind,
    TreeLocation,
    TreeStatus,
)
from app.modules.uploads.models import UploadedAsset
from app.modules.users.models import Follow, User, UserRole, UserSettings


def ensure_user(
    db,
    *,
    email: str,
    username: str,
    full_name: str,
    role: UserRole,
) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(
        email=email,
        username=username,
        full_name=full_name,
        password_hash=hash_password("Passw0rd123"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def ensure_user_settings(db, *, user_id, language_code: str) -> None:
    exists = db.query(UserSettings).filter(UserSettings.user_id == user_id).first()
    if exists:
        return
    db.add(UserSettings(user_id=user_id, language_code=language_code))


def ensure_follow(db, *, follower_id, following_id) -> None:
    exists = db.query(Follow).filter(Follow.follower_id == follower_id, Follow.following_id == following_id).first()
    if exists:
        return
    db.add(Follow(follower_id=follower_id, following_id=following_id))


def ensure_asset(db, *, owner_user_id, storage_key: str, file_name: str) -> UploadedAsset:
    asset = db.query(UploadedAsset).filter(UploadedAsset.storage_key == storage_key).first()
    if asset:
        return asset
    asset = UploadedAsset(
        owner_user_id=owner_user_id,
        storage_key=storage_key,
        url=f"http://localhost:9000/kok-assets/{storage_key}",
        content_type="image/jpeg",
        file_name=file_name,
        file_size=12345,
    )
    db.add(asset)
    db.flush()
    return asset


def ensure_tree(
    db,
    *,
    owner: User,
    moderator: User | None,
    name: str,
    status: TreeStatus,
    longitude: float,
    latitude: float,
    accuracy_meters: float,
    ai_status: str,
    ai_summary_json: str,
    front_asset: UploadedAsset,
    trunk_asset: UploadedAsset,
    leaves_asset: UploadedAsset,
    now: datetime,
) -> Tree:
    tree = db.query(Tree).filter(Tree.name == name, Tree.deleted_at.is_(None)).first()
    if tree:
        changed = False
        if tree.status != status:
            tree.status = status
            changed = True
        if tree.ai_status != ai_status:
            tree.ai_status = ai_status
            changed = True
        if tree.ai_model_version != "seed-demo":
            tree.ai_model_version = "seed-demo"
            changed = True
        if tree.ai_summary_json != ai_summary_json:
            tree.ai_summary_json = ai_summary_json
            changed = True
        if tree.ai_analyzed_at is None:
            tree.ai_analyzed_at = now
            changed = True
        if changed and status == TreeStatus.VERIFIED and moderator:
            has_verify_event = (
                db.query(TreeEvent)
                .filter(TreeEvent.tree_id == tree.id, TreeEvent.event_type == TreeEventType.VERIFIED)
                .first()
            )
            if not has_verify_event:
                db.add(
                    TreeEvent(
                        tree_id=tree.id,
                        actor_user_id=moderator.id,
                        event_type=TreeEventType.VERIFIED,
                        created_at=now,
                    )
                )
        return tree

    tree = Tree(
        owner_user_id=owner.id,
        name=name,
        status=status,
        captured_at=now,
        ai_status=ai_status,
        ai_model_version="seed-demo",
        ai_summary_json=ai_summary_json,
        ai_analyzed_at=now,
    )
    db.add(tree)
    db.flush()

    db.add_all(
        [
            TreeImage(tree_id=tree.id, uploaded_asset_id=front_asset.id, kind=TreeImageKind.FRONT),
            TreeImage(tree_id=tree.id, uploaded_asset_id=trunk_asset.id, kind=TreeImageKind.TRUNK),
            TreeImage(tree_id=tree.id, uploaded_asset_id=leaves_asset.id, kind=TreeImageKind.LEAVES),
            TreeLocation(
                tree_id=tree.id,
                location=WKTElement(f"POINT({longitude} {latitude})", srid=4326),
                accuracy_meters=accuracy_meters,
                source="mobile",
            ),
            TreeEvent(
                tree_id=tree.id,
                actor_user_id=owner.id,
                event_type=TreeEventType.REGISTERED,
                created_at=now,
            ),
        ]
    )
    if status == TreeStatus.VERIFIED and moderator:
        db.add(
            TreeEvent(
                tree_id=tree.id,
                actor_user_id=moderator.id,
                event_type=TreeEventType.VERIFIED,
                created_at=now,
            )
        )
    return tree


def ensure_post_bundle(
    db,
    *,
    author: User,
    tree: Tree,
    content: str,
    longitude: float,
    latitude: float,
    now: datetime,
    image_asset: UploadedAsset | None = None,
) -> SocialPost:
    post = db.query(SocialPost).filter(SocialPost.content == content).first()
    if post:
        if image_asset is None:
            # Historical demo rows referenced object keys that were never
            # uploaded. Do not keep advertising those broken images.
            db.query(SocialPostImage).filter(SocialPostImage.post_id == post.id).delete()
        return post
    post = SocialPost(
        author_user_id=author.id,
        tree_id=tree.id,
        content=content,
        client_created_at=now,
        location=WKTElement(f"POINT({longitude} {latitude})", srid=4326),
    )
    db.add(post)
    db.flush()
    if image_asset:
        db.add(SocialPostImage(post_id=post.id, uploaded_asset_id=image_asset.id))
    return post


def ensure_like(db, *, user_id, post_id) -> None:
    exists = db.query(SocialPostLike).filter(SocialPostLike.user_id == user_id, SocialPostLike.post_id == post_id).first()
    if exists:
        return
    db.add(SocialPostLike(user_id=user_id, post_id=post_id))


def ensure_comment(db, *, user_id, post_id, content: str) -> None:
    exists = (
        db.query(SocialPostComment)
        .filter(SocialPostComment.user_id == user_id, SocialPostComment.post_id == post_id, SocialPostComment.content == content)
        .first()
    )
    if exists:
        return
    db.add(SocialPostComment(user_id=user_id, post_id=post_id, content=content))


def ensure_achievement(db, *, code: str, title: str, description: str) -> Achievement:
    achievement = db.query(Achievement).filter(Achievement.code == code).first()
    if achievement:
        return achievement
    achievement = Achievement(code=code, title=title, description=description)
    db.add(achievement)
    db.flush()
    return achievement


def ensure_user_achievement(db, *, user_id, achievement_id) -> None:
    exists = (
        db.query(UserAchievement)
        .filter(UserAchievement.user_id == user_id, UserAchievement.achievement_id == achievement_id)
        .first()
    )
    if exists:
        return
    db.add(UserAchievement(user_id=user_id, achievement_id=achievement_id))


def ensure_notification(db, *, user_id, title: str, body: str, is_read: bool) -> None:
    exists = db.query(Notification).filter(Notification.user_id == user_id, Notification.title == title).first()
    if exists:
        return
    db.add(Notification(user_id=user_id, title=title, body=body, is_read=is_read))


def run() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        alice = ensure_user(
            db,
            email="alice@example.com",
            username="alice",
            full_name="Alice Green",
            role=UserRole.USER,
        )
        bob = ensure_user(
            db,
            email="bob@example.com",
            username="bob",
            full_name="Bob Leaf",
            role=UserRole.MODERATOR,
        )
        clara = ensure_user(
            db,
            email="clara@example.com",
            username="clara",
            full_name="Clara Forest",
            role=UserRole.USER,
        )

        ensure_user_settings(db, user_id=alice.id, language_code="en")
        ensure_user_settings(db, user_id=bob.id, language_code="ru")
        ensure_user_settings(db, user_id=clara.id, language_code="uz")
        ensure_follow(db, follower_id=clara.id, following_id=alice.id)
        ensure_follow(db, follower_id=alice.id, following_id=bob.id)

        alice_front = ensure_asset(db, owner_user_id=alice.id, storage_key="seed/alice-front.jpg", file_name="alice-front.jpg")
        alice_trunk = ensure_asset(db, owner_user_id=alice.id, storage_key="seed/alice-trunk.jpg", file_name="alice-trunk.jpg")
        alice_leaves = ensure_asset(db, owner_user_id=alice.id, storage_key="seed/alice-leaves.jpg", file_name="alice-leaves.jpg")
        clara_front = ensure_asset(db, owner_user_id=clara.id, storage_key="seed/clara-front.jpg", file_name="clara-front.jpg")
        clara_trunk = ensure_asset(db, owner_user_id=clara.id, storage_key="seed/clara-trunk.jpg", file_name="clara-trunk.jpg")
        clara_leaves = ensure_asset(db, owner_user_id=clara.id, storage_key="seed/clara-leaves.jpg", file_name="clara-leaves.jpg")

        sample_detection = (
            '{"tree_detected": true, "images_with_detections": 3, "max_confidence": 0.9821, '
            '"images": {"front": {"detected": true, "boxes_count": 1, "max_confidence": 0.9821}, '
            '"trunk": {"detected": true, "boxes_count": 1, "max_confidence": 0.9532}, '
            '"leaves": {"detected": true, "boxes_count": 1, "max_confidence": 0.9444}}}'
        )

        trees = [
            ensure_tree(
                db,
                owner=alice,
                moderator=bob,
                name="Oak on Main St",
                status=TreeStatus.VERIFIED,
                longitude=69.2401,
                latitude=41.2995,
                accuracy_meters=5,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=alice_front,
                trunk_asset=alice_trunk,
                leaves_asset=alice_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=clara,
                moderator=bob,
                name="Plane Tree by River Road",
                status=TreeStatus.VERIFIED,
                longitude=69.2551,
                latitude=41.3111,
                accuracy_meters=4,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=clara_front,
                trunk_asset=clara_trunk,
                leaves_asset=clara_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=alice,
                moderator=bob,
                name="Chestnut near Amir Temur Square",
                status=TreeStatus.VERIFIED,
                longitude=69.2797,
                latitude=41.3111,
                accuracy_meters=3,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=alice_front,
                trunk_asset=alice_trunk,
                leaves_asset=alice_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=alice,
                moderator=bob,
                name="Elm at Magic City Boulevard",
                status=TreeStatus.VERIFIED,
                longitude=69.2408,
                latitude=41.2927,
                accuracy_meters=6,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=alice_front,
                trunk_asset=alice_trunk,
                leaves_asset=alice_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=clara,
                moderator=bob,
                name="Pine by Alisher Navoi National Park",
                status=TreeStatus.VERIFIED,
                longitude=69.2389,
                latitude=41.3130,
                accuracy_meters=4,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=clara_front,
                trunk_asset=clara_trunk,
                leaves_asset=clara_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=clara,
                moderator=bob,
                name="Mulberry near Chorsu Bazaar",
                status=TreeStatus.VERIFIED,
                longitude=69.2325,
                latitude=41.3267,
                accuracy_meters=5,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=clara_front,
                trunk_asset=clara_trunk,
                leaves_asset=clara_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=alice,
                moderator=bob,
                name="Acacia on Taras Shevchenko Street",
                status=TreeStatus.VERIFIED,
                longitude=69.2762,
                latitude=41.3056,
                accuracy_meters=4,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=alice_front,
                trunk_asset=alice_trunk,
                leaves_asset=alice_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=alice,
                moderator=bob,
                name="Cedar in Tashkent City Park",
                status=TreeStatus.VERIFIED,
                longitude=69.2457,
                latitude=41.3164,
                accuracy_meters=3,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=alice_front,
                trunk_asset=alice_trunk,
                leaves_asset=alice_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=clara,
                moderator=bob,
                name="Willow beside Ankhor Canal",
                status=TreeStatus.VERIFIED,
                longitude=69.2503,
                latitude=41.3278,
                accuracy_meters=5,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=clara_front,
                trunk_asset=clara_trunk,
                leaves_asset=clara_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=alice,
                moderator=bob,
                name="Maple near Minor Mosque",
                status=TreeStatus.VERIFIED,
                longitude=69.2788,
                latitude=41.3385,
                accuracy_meters=3,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=alice_front,
                trunk_asset=alice_trunk,
                leaves_asset=alice_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=clara,
                moderator=bob,
                name="Poplar by Seoul Mun",
                status=TreeStatus.VERIFIED,
                longitude=69.2814,
                latitude=41.2899,
                accuracy_meters=5,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=clara_front,
                trunk_asset=clara_trunk,
                leaves_asset=clara_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=alice,
                moderator=bob,
                name="Sycamore at Broadway Alley",
                status=TreeStatus.VERIFIED,
                longitude=69.2724,
                latitude=41.3079,
                accuracy_meters=4,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=alice_front,
                trunk_asset=alice_trunk,
                leaves_asset=alice_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=clara,
                moderator=bob,
                name="Birch near Eco Park",
                status=TreeStatus.VERIFIED,
                longitude=69.3018,
                latitude=41.3301,
                accuracy_meters=4,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=clara_front,
                trunk_asset=clara_trunk,
                leaves_asset=clara_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=alice,
                moderator=bob,
                name="Linden on Shota Rustaveli Avenue",
                status=TreeStatus.VERIFIED,
                longitude=69.2547,
                latitude=41.2854,
                accuracy_meters=3,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=alice_front,
                trunk_asset=alice_trunk,
                leaves_asset=alice_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=clara,
                moderator=bob,
                name="Ash tree near Yunusobod Bazaar",
                status=TreeStatus.VERIFIED,
                longitude=69.2886,
                latitude=41.3662,
                accuracy_meters=5,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=clara_front,
                trunk_asset=clara_trunk,
                leaves_asset=clara_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=alice,
                moderator=bob,
                name="Cypress by White Mosque",
                status=TreeStatus.VERIFIED,
                longitude=69.2148,
                latitude=41.3194,
                accuracy_meters=4,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=alice_front,
                trunk_asset=alice_trunk,
                leaves_asset=alice_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=clara,
                moderator=bob,
                name="Walnut near Tashkent TV Tower",
                status=TreeStatus.VERIFIED,
                longitude=69.2869,
                latitude=41.3441,
                accuracy_meters=6,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=clara_front,
                trunk_asset=clara_trunk,
                leaves_asset=clara_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=alice,
                moderator=bob,
                name="Juniper in Japanese Garden",
                status=TreeStatus.VERIFIED,
                longitude=69.2897,
                latitude=41.3380,
                accuracy_meters=3,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=alice_front,
                trunk_asset=alice_trunk,
                leaves_asset=alice_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=clara,
                moderator=bob,
                name="Apricot tree near Samarkand Darvoza",
                status=TreeStatus.VERIFIED,
                longitude=69.2096,
                latitude=41.3162,
                accuracy_meters=5,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=clara_front,
                trunk_asset=clara_trunk,
                leaves_asset=clara_leaves,
                now=now,
            ),
            ensure_tree(
                db,
                owner=alice,
                moderator=bob,
                name="Hazel near Lokomotiv Park",
                status=TreeStatus.VERIFIED,
                longitude=69.3202,
                latitude=41.2922,
                accuracy_meters=4,
                ai_status="completed",
                ai_summary_json=sample_detection,
                front_asset=alice_front,
                trunk_asset=alice_trunk,
                leaves_asset=alice_leaves,
                now=now,
            ),
        ]

        post_one = ensure_post_bundle(
            db,
            author=alice,
            tree=trees[0],
            content="Registered this beautiful tree today!",
            longitude=69.2401,
            latitude=41.2995,
            now=now,
            image_asset=None,
        )
        post_two = ensure_post_bundle(
            db,
            author=clara,
            tree=trees[1],
            content="Found another tree worth tracking.",
            longitude=69.2551,
            latitude=41.3111,
            now=now,
            image_asset=None,
        )

        ensure_like(db, user_id=bob.id, post_id=post_one.id)
        ensure_like(db, user_id=clara.id, post_id=post_one.id)
        ensure_comment(db, user_id=bob.id, post_id=post_one.id, content="Great registration. This looks healthy.")
        ensure_comment(db, user_id=alice.id, post_id=post_two.id, content="Nice find. We should monitor this area.")

        first_tree = ensure_achievement(
            db,
            code="first_tree",
            title="First Tree",
            description="Registered your first tree",
        )
        urban_scout = ensure_achievement(
            db,
            code="urban_scout",
            title="Urban Scout",
            description="Registered and shared your discoveries in the city.",
        )

        ensure_user_achievement(db, user_id=alice.id, achievement_id=first_tree.id)
        ensure_user_achievement(db, user_id=alice.id, achievement_id=urban_scout.id)
        ensure_user_achievement(db, user_id=clara.id, achievement_id=first_tree.id)

        ensure_notification(
            db,
            user_id=alice.id,
            title="Welcome",
            body="Thanks for joining KOK.AI",
            is_read=False,
        )
        ensure_notification(
            db,
            user_id=alice.id,
            title="Tree verified",
            body="Your Oak on Main St has been verified.",
            is_read=False,
        )
        ensure_notification(
            db,
            user_id=clara.id,
            title="New follower",
            body="Alice started following your activity.",
            is_read=True,
        )

        db.commit()
        print(f"Seed complete: {len(trees)} Tashkent trees available")
    finally:
        db.close()


if __name__ == "__main__":
    run()
