"""Billing API — subscription status, trial info, plan management."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.user import User
from src.models.subscription import Subscription, SubscriptionStatus, Plan
from src.auth import get_current_user

router = APIRouter(prefix="/api/billing", tags=["billing"])


class SubscriptionResponse(BaseModel):
    plan: str
    status: str
    trial_started_at: str | None
    trial_ends_at: str | None
    current_period_start: str | None
    current_period_end: str | None
    days_left: int | None
    access_granted: bool


@router.get("/status")
async def billing_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionResponse:
    result = await db.execute(
        select(Subscription).where(Subscription.tenant_id == current_user.tenant_id)
    )
    sub = result.scalar_one_or_none()

    if sub is None:
        # No subscription record — shouldn't happen, but gate access
        return SubscriptionResponse(
            plan="starter",
            status="none",
            trial_started_at=None,
            trial_ends_at=None,
            current_period_start=None,
            current_period_end=None,
            days_left=None,
            access_granted=False,
        )

    # Check trial expiry
    if sub.check_trial_expired():
        sub.status = SubscriptionStatus.EXPIRED
        await db.commit()

    import math
    from datetime import datetime, timezone

    days_left = None
    if sub.status in (SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE):
        if sub.trial_ends_at:
            delta = sub.trial_ends_at - datetime.now(timezone.utc)
            days_left = max(0, math.ceil(delta.total_seconds() / 86400))
        elif sub.current_period_end:
            delta = sub.current_period_end - datetime.now(timezone.utc)
            days_left = max(0, math.ceil(delta.total_seconds() / 86400))

    return SubscriptionResponse(
        plan=sub.plan.value,
        status=sub.status.value,
        trial_started_at=sub.trial_started_at.isoformat() if sub.trial_started_at else None,
        trial_ends_at=sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
        current_period_start=sub.current_period_start.isoformat()
        if sub.current_period_start
        else None,
        current_period_end=sub.current_period_end.isoformat()
        if sub.current_period_end
        else None,
        days_left=days_left,
        access_granted=sub.is_access_granted(),
    )
