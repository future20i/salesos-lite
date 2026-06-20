"""Notification preferences API — GET/PUT per-user notification prefs."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.auth import get_current_user
from src.models.user import User
from src.models.notification_pref import NotificationPref

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationPrefResponse(BaseModel):
    desktop_enabled: bool
    sound_enabled: bool


class NotificationPrefUpdate(BaseModel):
    desktop_enabled: bool | None = None
    sound_enabled: bool | None = None


async def _get_or_create_pref(
    user: User, db: AsyncSession
) -> NotificationPref:
    """Get existing prefs or create with defaults."""
    result = await db.execute(
        select(NotificationPref).where(NotificationPref.user_id == user.id)
    )
    pref = result.scalar_one_or_none()
    if pref is None:
        pref = NotificationPref(
            tenant_id=user.tenant_id,
            user_id=user.id,
            desktop_enabled=True,
            sound_enabled=False,
        )
        db.add(pref)
        await db.commit()
        await db.refresh(pref)
    return pref


@router.get("/preferences")
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationPrefResponse:
    pref = await _get_or_create_pref(current_user, db)
    return NotificationPrefResponse(
        desktop_enabled=pref.desktop_enabled,
        sound_enabled=pref.sound_enabled,
    )


@router.put("/preferences")
async def update_preferences(
    body: NotificationPrefUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationPrefResponse:
    pref = await _get_or_create_pref(current_user, db)
    if body.desktop_enabled is not None:
        pref.desktop_enabled = body.desktop_enabled
    if body.sound_enabled is not None:
        pref.sound_enabled = body.sound_enabled
    await db.commit()
    await db.refresh(pref)
    return NotificationPrefResponse(
        desktop_enabled=pref.desktop_enabled,
        sound_enabled=pref.sound_enabled,
    )
