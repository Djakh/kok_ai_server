import asyncio
import uuid

from celery import Celery

from app.common.config import get_settings

settings = get_settings()

celery_app = Celery(
    "kok_ai",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.beat_schedule = {
    "kindwise-usage-every-15-minutes": {
        "task": "tasks.monitor_kindwise_usage",
        "schedule": 900.0,
    },
    "outbox-every-minute": {"task": "tasks.process_outbox", "schedule": 60.0},
    "cleanup-abandoned-uploads-hourly": {
        "task": "tasks.cleanup_abandoned_uploads",
        "schedule": 3600.0,
    },
}


@celery_app.task(name="tasks.image_post_process")
def image_post_process(upload_id: str) -> dict[str, str]:
    return {"status": "queued", "upload_id": upload_id}


@celery_app.task(name="tasks.dispatch_notification")
def dispatch_notification(notification_id: str) -> dict[str, str]:
    return {"status": "queued", "notification_id": notification_id}


@celery_app.task(name="tasks.evaluate_achievements")
def evaluate_achievements(user_id: str) -> dict[str, str]:
    return {"status": "queued", "user_id": user_id}


@celery_app.task(name="tasks.analyze_tree_images")
def analyze_tree_images(tree_id: str) -> dict[str, str]:
    from app.common.db.session import SessionLocal
    from app.modules.trees.detector import TreeDetectionService

    db = SessionLocal()
    try:
        TreeDetectionService(db).analyze_tree(uuid.UUID(tree_id))
        return {"status": "queued", "tree_id": tree_id}
    finally:
        db.close()


@celery_app.task(name="tasks.monitor_kindwise_usage")
def monitor_kindwise_usage() -> dict[str, str | float | bool]:
    from app.common.observability import set_gauge
    from app.modules.tree_analyses.kindwise import KindwisePlantIdClient

    if settings.plant_analysis_provider != "kindwise" or not settings.kindwise_api_key:
        set_gauge("kok_ai_kindwise_active", 0)
        return {"status": "inactive", "active": False}
    usage = asyncio.run(KindwisePlantIdClient(settings).usage_info())
    remaining = float(usage.get("remaining", usage.get("remaining_credits", 0)) or 0)
    active = bool(usage.get("active", False))
    can_use = bool(usage.get("can_use_credits", False))
    set_gauge("kok_ai_kindwise_remaining_credits", remaining)
    set_gauge("kok_ai_kindwise_active", 1 if active else 0)
    set_gauge("kok_ai_kindwise_can_use_credits", 1 if can_use else 0)
    return {"remaining_credits": remaining, "active": active, "can_use_credits": can_use}


@celery_app.task(name="tasks.process_outbox")
def process_outbox() -> dict[str, int]:
    from datetime import datetime, timezone

    from app.common.db.outbox import OutboxEvent
    from app.common.db.session import SessionLocal

    db = SessionLocal()
    processed = 0
    try:
        rows = (
            db.query(OutboxEvent)
            .filter(
                OutboxEvent.status == "pending",
                OutboxEvent.available_at <= datetime.now(timezone.utc),
            )
            .with_for_update(skip_locked=True)
            .limit(100)
            .all()
        )
        for row in rows:
            if row.event_type == "tree.registered" and row.payload.get("owner_id"):
                evaluate_achievements.delay(row.payload["owner_id"])
            row.status = "published"
            row.published_at = datetime.now(timezone.utc)
            processed += 1
        db.commit()
        return {"processed": processed}
    finally:
        db.close()


@celery_app.task(name="tasks.cleanup_abandoned_uploads")
def cleanup_abandoned_uploads() -> dict[str, int]:
    from datetime import datetime, timezone

    from app.common.db.session import SessionLocal
    from app.common.storage.s3 import get_s3_client
    from app.modules.uploads.models import UploadedAsset

    db = SessionLocal()
    cleaned = 0
    try:
        rows = (
            db.query(UploadedAsset)
            .filter(
                UploadedAsset.status == "available",
                UploadedAsset.expires_at.is_not(None),
                UploadedAsset.expires_at <= datetime.now(timezone.utc),
            )
            .limit(500)
            .all()
        )
        client = get_s3_client()
        for row in rows:
            keys = [row.storage_key, row.original_storage_key]
            client.delete_objects(
                Bucket=settings.s3_bucket,
                Delete={"Objects": [{"Key": key} for key in keys if key], "Quiet": True},
            )
            row.status = "expired"
            cleaned += 1
        db.commit()
        return {"cleaned": cleaned}
    finally:
        db.close()
