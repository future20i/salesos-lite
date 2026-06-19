"""Auth: JWT + RBAC with hashlib password hashing (zero extra deps)."""
import hashlib
import os
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import User, UserRole
from database import get_db

# ── Config ─────────────────────────────────────────────────────────
JWT_SECRET = os.environ.get("JWT_SECRET", "salesos-lite-dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

security = HTTPBearer()


# ── Password helpers ───────────────────────────────────────────────

def _hash_salt(password: str, salt: str | None = None) -> str:
    """PBKDF2-SHA256 with hex salt (96 chars total)."""
    if salt is None:
        salt = os.urandom(32).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode() if isinstance(salt, str) else salt, 600_000)
    return f"pbkdf2:sha256:600000${salt}${dk.hex()}"


def hash_password(password: str) -> str:
    return _hash_salt(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Compare plaintext against stored PBKDF2 hash."""
    try:
        _, salt, dk = hashed.split("$", 2)
    except ValueError:
        return False
    return _hash_salt(plain, salt) == hashed


# ── Token helpers ──────────────────────────────────────────────────

def create_token(user_id: int, username: str, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── Dependency: current user ───────────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)
    user = db.get(User, int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


# ── Role gates ─────────────────────────────────────────────────────

def require_role(*roles: UserRole):
    def gate(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Requires role: {[r.value for r in roles]}")
        return user
    return gate


# ── Seed default users ─────────────────────────────────────────────

def seed_users(db: Session):
    defaults = [
        ("admin", "admin123", UserRole.ADMIN),
        ("manager", "mgr123", UserRole.MANAGER),
        ("rep", "rep123", UserRole.REP),
    ]
    for username, password, role in defaults:
        if db.execute(select(User).where(User.username == username)).scalars().first():
            continue
        db.add(User(username=username, password_hash=hash_password(password), role=role))
    db.commit()
