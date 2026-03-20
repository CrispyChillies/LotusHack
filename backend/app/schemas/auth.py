from pydantic import BaseModel, EmailStr
from typing import Optional
from uuid import UUID
from datetime import datetime


# ---------- Request schemas ----------

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    role: Optional[str] = None  # 'patient' | 'family_member'


class UserLogin(BaseModel):
    email: EmailStr
    password: str


# ---------- Response schemas ----------

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int          # giây
    refresh_token: str


class UserProfile(BaseModel):
    id: UUID
    email: Optional[str]
    full_name: Optional[str]
    role: Optional[str]
    persona: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True
