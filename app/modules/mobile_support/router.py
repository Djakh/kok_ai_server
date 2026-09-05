import uuid

from fastapi import APIRouter, Depends, status

from app.common.rate_limit.dependencies import WriteRateLimit
from app.common.responses.envelope import success_response
from app.common.security.dependencies import CurrentUser, get_current_user
from app.modules.mobile_support.dependencies import get_mobile_support_service
from app.modules.mobile_support.schemas import (
    DevicePatchRequest,
    DeviceUpsertRequest,
    ReportCreateRequest,
    TreeIssueCreateRequest,
)
from app.modules.mobile_support.service import MobileSupportService
from app.modules.users.schemas import UserPublic

router = APIRouter(tags=["mobile support"])


@router.post("/devices", status_code=status.HTTP_201_CREATED, dependencies=[WriteRateLimit])
def register_device(
    payload: DeviceUpsertRequest,
    current: CurrentUser = Depends(get_current_user),
    service: MobileSupportService = Depends(get_mobile_support_service),
):
    row = service.upsert_device(current.user.id, payload)
    return success_response(service.device_payload(row), status_code=201)


@router.patch("/devices/{installation_id}", dependencies=[WriteRateLimit])
def patch_device(
    installation_id: str,
    payload: DevicePatchRequest,
    current: CurrentUser = Depends(get_current_user),
    service: MobileSupportService = Depends(get_mobile_support_service),
):
    row = service.patch_device(current.user.id, installation_id, payload)
    return success_response(service.device_payload(row))


@router.delete("/devices/{installation_id}", dependencies=[WriteRateLimit])
def delete_device(
    installation_id: str,
    current: CurrentUser = Depends(get_current_user),
    service: MobileSupportService = Depends(get_mobile_support_service),
):
    service.delete_device(current.user.id, installation_id)
    return success_response({"deleted": True})


@router.post("/reports", status_code=status.HTTP_201_CREATED, dependencies=[WriteRateLimit])
def create_report(
    payload: ReportCreateRequest,
    current: CurrentUser = Depends(get_current_user),
    service: MobileSupportService = Depends(get_mobile_support_service),
):
    row = service.create_report(current.user.id, payload)
    return success_response(service.report_payload(row), status_code=201)


@router.post("/users/{user_id}/block", dependencies=[WriteRateLimit])
def block_user(
    user_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: MobileSupportService = Depends(get_mobile_support_service),
):
    service.block_user(current.user.id, user_id)
    return success_response({"blocked": True, "user_id": str(user_id)})


@router.delete("/users/{user_id}/block", dependencies=[WriteRateLimit])
def unblock_user(
    user_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    service: MobileSupportService = Depends(get_mobile_support_service),
):
    service.unblock_user(current.user.id, user_id)
    return success_response({"blocked": False, "user_id": str(user_id)})


@router.get("/users/me/blocked")
def blocked_users(
    current: CurrentUser = Depends(get_current_user),
    service: MobileSupportService = Depends(get_mobile_support_service),
):
    items = [
        UserPublic.model_validate(row).model_dump(mode="json")
        for row in service.blocked_users(current.user.id)
    ]
    return success_response({"items": items, "next_cursor": None})


@router.post(
    "/trees/{tree_id}/issues",
    status_code=status.HTTP_201_CREATED,
    dependencies=[WriteRateLimit],
)
def create_tree_issue(
    tree_id: uuid.UUID,
    payload: TreeIssueCreateRequest,
    current: CurrentUser = Depends(get_current_user),
    service: MobileSupportService = Depends(get_mobile_support_service),
):
    row = service.create_tree_issue(current.user.id, tree_id, payload)
    return success_response(service.issue_payload(row), status_code=201)


@router.get("/trees/issues/mine")
def my_tree_issues(
    current: CurrentUser = Depends(get_current_user),
    service: MobileSupportService = Depends(get_mobile_support_service),
):
    items = [service.issue_payload(row) for row in service.list_tree_issues(current.user.id)]
    return success_response({"items": items, "next_cursor": None})
