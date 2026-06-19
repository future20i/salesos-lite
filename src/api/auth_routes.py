import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.tenant import Tenant
from src.models.user import User, UserRole
from src.auth import (
    hash_password,
    verify_password,
    create_token,
    get_current_user,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ───────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    company_name: str
    username: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    user: dict


class UserResponse(BaseModel):
    id: str
    username: str
    role: str
    tenant_id: str


# ── Routes ────────────────────────────────────────────────────────

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    # Check for duplicate email
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Create tenant
    tenant = Tenant(name=body.company_name)
    db.add(tenant)
    await db.flush()

    # Create admin user
    user = User(
        tenant_id=tenant.id,
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=UserRole.ADMIN,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_token(str(user.id), str(user.tenant_id), user.role.value)
    return AuthResponse(
        token=token,
        user={
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role.value,
            "tenant_id": str(user.tenant_id),
        },
    )


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_token(str(user.id), str(user.tenant_id), user.role.value)
    return AuthResponse(
        token=token,
        user={
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role.value,
            "tenant_id": str(user.tenant_id),
        },
    )


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return UserResponse(
        id=str(current_user.id),
        username=current_user.username,
        role=current_user.role.value,
        tenant_id=str(current_user.tenant_id),
    )
