"""
Auth Service – Memory Companion (Neon/Postgres)

Required environment variables in .env:
    DATABASE_URL=postgresql://<user>:<password>@<host>/<db>?sslmode=require
    JWT_SECRET_KEY=<strong-random-secret>

Optional:
    ACCESS_TOKEN_EXPIRE_MINUTES=60
    REFRESH_TOKEN_EXPIRE_DAYS=30
"""

from __future__ import annotations

import os
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from uuid import UUID, uuid4

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
import psycopg
from psycopg.rows import dict_row

from app.schemas.auth import TokenResponse, UserProfile, UserRegister, UserLogin

load_dotenv()

_bearer_scheme = HTTPBearer()
_PBKDF2_ITERATIONS = 390000


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(dk).decode("ascii")
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt_b64}${hash_b64}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_str, salt_b64, hash_b64 = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(hash_b64.encode("ascii"))
    except Exception:
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate, expected)


def _get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _get_database_url() -> str:
    return _get_env("DATABASE_URL")


def _get_jwt_secret() -> str:
    return _get_env("JWT_SECRET_KEY")


def _access_ttl_minutes() -> int:
    return int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))


def _refresh_ttl_days() -> int:
    return int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

# ------------------------------------------------------------------ #
#  Database helpers                                                    #
# ------------------------------------------------------------------ #

def _connect() -> psycopg.Connection:
    return psycopg.connect(_get_database_url(), row_factory=dict_row)


@lru_cache(maxsize=1)
def _init_db() -> None:
    """Create auth credential table if it does not exist yet."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_credentials (
                    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    email VARCHAR UNIQUE NOT NULL,
                    password_hash VARCHAR NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                """
            )
        conn.commit()


def _create_token(user_id: str, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")


def _decode_token(token: str) -> dict:
    return jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])


# ------------------------------------------------------------------ #
#  Register                                                           #
# ------------------------------------------------------------------ #

async def register_user(payload: UserRegister) -> UserProfile:
    _init_db()
    user_id = uuid4()
    password_hash = _hash_password(payload.password)

    # Create application profile + credential record in one transaction.
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM user_credentials WHERE LOWER(email) = LOWER(%s)",
                    (payload.email,),
                )
                if cur.fetchone():
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Email đã được sử dụng.",
                    )

                cur.execute(
                    """
                    INSERT INTO users (id, email, full_name, role, created_at)
                    VALUES (%s, %s, %s, %s, now())
                    """,
                    (str(user_id), payload.email, payload.full_name, payload.role),
                )
                cur.execute(
                    """
                    INSERT INTO user_credentials (user_id, email, password_hash)
                    VALUES (%s, %s, %s)
                    """,
                    (str(user_id), payload.email, password_hash),
                )
            conn.commit()
    except HTTPException:
        raise
    except psycopg.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Đăng ký thất bại: {exc}",
        )

    return await _fetch_profile(str(user_id))


# ------------------------------------------------------------------ #
#  Login                                                              #
# ------------------------------------------------------------------ #

async def login_user(payload: UserLogin) -> TokenResponse:
    """Xác thực bằng email/password và trả về access/refresh JWT."""
    _init_db()

    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT user_id, password_hash
                    FROM user_credentials
                    WHERE LOWER(email) = LOWER(%s)
                    """,
                    (payload.email,),
                )
                row = cur.fetchone()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Sai email hoặc mật khẩu: {exc}",
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai email hoặc mật khẩu.",
        )

    password_ok = _verify_password(payload.password, row["password_hash"])
    if not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai email hoặc mật khẩu.",
        )

    user_id = str(row["user_id"])
    access_expires = timedelta(minutes=_access_ttl_minutes())
    refresh_expires = timedelta(days=_refresh_ttl_days())

    access_token = _create_token(user_id, "access", access_expires)
    refresh_token = _create_token(user_id, "refresh", refresh_expires)

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=int(access_expires.total_seconds()),
        refresh_token=refresh_token,
    )


# ------------------------------------------------------------------ #
#  Dependency: get_current_user                                       #
# ------------------------------------------------------------------ #

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> UserProfile:
    """FastAPI dependency – xác thực access JWT từ Authorization header."""
    token = credentials.credentials

    try:
        payload = _decode_token(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token không hợp lệ hoặc đã hết hạn: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không phải access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không chứa user id.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await _fetch_profile(user_id)


# ------------------------------------------------------------------ #
#  Internal helper                                                    #
# ------------------------------------------------------------------ #

async def _fetch_profile(user_id: str) -> UserProfile:
    """Lấy thông tin từ users theo id."""
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, full_name, role, persona, created_at
                    FROM users
                    WHERE id = %s
                    """,
                    (str(UUID(user_id)),),
                )
                row = cur.fetchone()
    except (ValueError, psycopg.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy profile cho user {user_id}: {exc}",
        )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy profile cho user {user_id}",
        )

    return UserProfile(**row)
