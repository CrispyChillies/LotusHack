from fastapi import APIRouter, Depends

from app.schemas.auth import UserProfile
from app.schemas.relation import JoinByQRRequest, JoinByQRResponse
from app.services.auth_service import get_current_user
from app.services.relation_service import join_family_by_qr

router = APIRouter()


@router.post("/join-by-qr", response_model=JoinByQRResponse)
async def join_by_qr(
    payload: JoinByQRRequest,
    current_user: UserProfile = Depends(get_current_user),
):
    return await join_family_by_qr(current_user.id, payload)
