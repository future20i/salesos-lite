import os
import hashlib
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.user import User, UserRole

JWT_SECRET = os.environ.get(
    "JWT_SECRET",
    hashlib.sha256(os.urandom(64)).hexdigest(),
)
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24

security_scheme = HTTPBearer(auto_error=False)


# ── Password hashing ──────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Return salt_hex:key_hex using PBKDF2-SHA256."""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000)
    return f"{salt.hex()}:{key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a salt_hex:key_hex string."""
    try:
        salt_hex, key_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected_key = bytes.fromhex(key_hex)
    except (ValueError, AttributeError):
        return False
    actual_key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000)
    return actual_key == expected_key


# ── JWT ───────────────────────────────────────────────────────────

def create_token(user_id: str, tenant_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises HTTPException on failure."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


# ── Dependencies ──────────────────────────────────────────────────

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency — extract User from JWT Bearer token."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    payload = decode_token(credentials.credentials)
    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload"
        )
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    # Set tenant context on request for the tenant_context_middleware
    tenant_id = payload.get("tenant_id")
    if tenant_id:
        request.state.tenant_id = tenant_id
    return user


def require_role(*roles: UserRole):
    """Factory — returns a dependency that checks the current user's role."""
    async def _role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of {[r.value for r in roles]}",
            )
        return current_user
    return _role_checker
