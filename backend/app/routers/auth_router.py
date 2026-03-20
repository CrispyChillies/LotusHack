"""
Auth Router – Memory Companion
Gắn vào main app:
    from app.routers.auth_router import router as auth_router
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])
"""

from fastapi import APIRouter, Depends

from app.schemas.auth import TokenResponse, UserProfile, UserRegister, UserLogin
from app.services.auth_service import (
    get_current_user,
    login_user,
    register_user,
)

router = APIRouter()


@router.post("/register", response_model=UserProfile, status_code=201)
async def register(payload: UserRegister):
    """
    Tạo tài khoản mới.
    - Supabase Auth tạo user trong auth.users
    - Trigger tự động INSERT vào public.users
    - Service cập nhật thêm full_name, role
    """
    return await register_user(payload)


@router.post("/login", response_model=TokenResponse)
async def login(payload: UserLogin):
    """Đăng nhập, trả về JWT access_token."""
    return await login_user(payload)


@router.get("/me", response_model=UserProfile)
async def me(current_user: UserProfile = Depends(get_current_user)):
    """Trả về thông tin user hiện tại (yêu cầu Bearer token)."""
    return current_user
