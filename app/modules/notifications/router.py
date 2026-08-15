import uuid

from fastapi import APIRouter, Depends

from app.common.responses.envelope import success_response
from app.common.security.dependencies import CurrentUser, get_current_user
from app.modules.notifications.dependencies import get_notification_service
from app.modules.notifications.service import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    current: CurrentUser = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    rows = service.repo.list_for_user(current.user.id)
    return success_response(
        [
            {
                "id": str(x.id),
                "title": x.title,
                "body": x.body,
                "is_read": x.is_read,
                "created_at": x.created_at,
            }
            for x in rows
        ]
    )


@router.patch("/read-all")
def read_all(
    current: CurrentUser = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    count = service.mark_all_read(current.user.id)
    return success_response({"updated": count})


@router.patch("/{notification_id}/read")
def read_one(
    notification_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    service.mark_read(notification_id, current.user.id)
    return success_response({"read": True})
