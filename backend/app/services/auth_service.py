"""
Auth Service – Memory Companion
Sử dụng thư viện: supabase-py (supabase>=2.x)

Cài đặt:
    pip install supabase python-dotenv

Biến môi trường cần có trong .env:
    SUPABASE_URL=https://<project>.supabase.co
    SUPABASE_ANON_KEY=<anon-key>
    SUPABASE_SERVICE_ROLE_KEY=<service-role-key>  # chỉ dùng phía server
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from supabase import Client, create_client

from app.schemas.auth import TokenResponse, UserProfile, UserRegister, UserLogin

load_dotenv()

# ------------------------------------------------------------------ #
#  Supabase client factory                                            #
# ------------------------------------------------------------------ #

@lru_cache(maxsize=1)
def _get_anon_client() -> Client:
    """Client dùng anon key – phù hợp với Auth operations (sign-up/sign-in)."""
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_ANON_KEY"],
    )


@lru_cache(maxsize=1)
def _get_service_client() -> Client:
    """
    Client dùng service_role key – bypass RLS, chỉ dùng trong backend.
    KHÔNG BAO GIỜ expose key này ra phía client.
    """
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )


# ------------------------------------------------------------------ #
#  Register                                                           #
# ------------------------------------------------------------------ #

async def register_user(payload: UserRegister) -> UserProfile:
    """
    1. Tạo user trong Supabase Auth  →  trigger tự INSERT vào public.users
    2. Cập nhật thêm full_name / role vào public.users bằng service client
    """
    anon = _get_anon_client()

    # --- Bước 1: Tạo tài khoản Auth ---
    try:
        auth_response = anon.auth.sign_up(
            {"email": payload.email, "password": payload.password}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Đăng ký thất bại: {exc}",
        )

    if auth_response.user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không thể tạo tài khoản. Email có thể đã được sử dụng.",
        )

    user_id = str(auth_response.user.id)

    # --- Bước 2: Cập nhật thêm thông tin vào public.users ---
    #     Trigger đã tạo sẵn dòng có id + email, ta chỉ UPDATE thêm field.
    update_data: dict = {}
    if payload.full_name:
        update_data["full_name"] = payload.full_name
    if payload.role:
        update_data["role"] = payload.role

    if update_data:
        service = _get_service_client()
        try:
            service.table("users").update(update_data).eq("id", user_id).execute()
        except Exception as exc:
            # Không raise – Auth user đã tạo xong; chỉ log lỗi phụ
            print(f"[WARN] Không cập nhật được public.users cho {user_id}: {exc}")

    # --- Bước 3: Trả về profile ---
    return await _fetch_profile(user_id)


# ------------------------------------------------------------------ #
#  Login                                                              #
# ------------------------------------------------------------------ #

async def login_user(payload: UserLogin) -> TokenResponse:
    """Xác thực và trả về JWT (access_token + refresh_token)."""
    anon = _get_anon_client()

    try:
        auth_response = anon.auth.sign_in_with_password(
            {"email": payload.email, "password": payload.password}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Sai email hoặc mật khẩu: {exc}",
        )

    session = auth_response.session
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Đăng nhập thất bại – không có session.",
        )

    return TokenResponse(
        access_token=session.access_token,
        token_type="bearer",
        expires_in=session.expires_in,
        refresh_token=session.refresh_token,
    )


# ------------------------------------------------------------------ #
#  Dependency: get_current_user                                       #
# ------------------------------------------------------------------ #

_bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> UserProfile:
    """
    FastAPI dependency – xác thực JWT từ Authorization header.

    Usage trong router:
        @router.get("/me")
        async def me(user: UserProfile = Depends(get_current_user)):
            return user
    """
    token = credentials.credentials
    service = _get_service_client()

    # Verify token thông qua Supabase Auth API
    try:
        user_response = service.auth.get_user(token)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token không hợp lệ hoặc đã hết hạn: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user_response.user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Không xác định được người dùng từ token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = str(user_response.user.id)
    return await _fetch_profile(user_id)


# ------------------------------------------------------------------ #
#  Internal helper                                                    #
# ------------------------------------------------------------------ #

async def _fetch_profile(user_id: str) -> UserProfile:
    """Lấy thông tin từ public.users theo id."""
    service = _get_service_client()
    try:
        result = (
            service.table("users")
            .select("id, email, full_name, role, persona, created_at")
            .eq("id", user_id)
            .single()
            .execute()
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy profile cho user {user_id}: {exc}",
        )

    return UserProfile(**result.data)
