"""Dashboard API — conversion funnel, lead stats, team performance."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.lead import Lead, LeadStatus, Intent
from src.models.user import User
from src.auth import get_current_user

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class FunnelStep(BaseModel):
    label: str
    count: int
    rate: float  # percentage of total


class DashboardResponse(BaseModel):
    total_leads: int
    funnel: list[FunnelStep]
    by_channel: dict[str, int]
    by_intent: dict[str, int]
    today_new: int
    week_new: int


_status_order = [
    ("新增", [LeadStatus.NEW]),
    ("跟进中", [LeadStatus.FOLLOWING]),
    ("报价", [LeadStatus.QUOTED]),
    ("样品", [LeadStatus.SAMPLED]),
    ("谈判", [LeadStatus.NEGOTIATING]),
]


async def _get_dashboard_data(tenant_id, db: AsyncSession) -> DashboardResponse:
    # Total leads
    total_result = await db.execute(
        select(func.count(Lead.id)).where(Lead.tenant_id == tenant_id)
    )
    total = total_result.scalar() or 0

    # Funnel by status
    funnel = []
    for label, statuses in _status_order:
        result = await db.execute(
            select(func.count(Lead.id)).where(
                Lead.tenant_id == tenant_id,
                Lead.status.in_(statuses),
            )
        )
        count = result.scalar() or 0
        rate = round(count / total * 100, 1) if total > 0 else 0
        funnel.append(FunnelStep(label=label, count=count, rate=rate))

    # By channel
    result = await db.execute(
        select(Lead.channel, func.count(Lead.id))
        .where(Lead.tenant_id == tenant_id)
        .group_by(Lead.channel)
    )
    by_channel = {r[0].value if hasattr(r[0], 'value') else r[0]: r[1] for r in result.all()}

    # By intent
    result = await db.execute(
        select(Lead.intent, func.count(Lead.id))
        .where(Lead.tenant_id == tenant_id)
        .group_by(Lead.intent)
    )
    by_intent = {}
    for r in result.all():
        key = r[0].value if r[0] and hasattr(r[0], 'value') else str(r[0] or 'unknown')
        by_intent[key] = r[1]

    # Today new
    from datetime import datetime, timezone, timedelta
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.count(Lead.id)).where(
            Lead.tenant_id == tenant_id,
            Lead.created_at >= today_start,
        )
    )
    today_new = result.scalar() or 0

    # This week new
    week_start = today_start - timedelta(days=today_start.weekday())
    result = await db.execute(
        select(func.count(Lead.id)).where(
            Lead.tenant_id == tenant_id,
            Lead.created_at >= week_start,
        )
    )
    week_new = result.scalar() or 0

    return DashboardResponse(
        total_leads=total,
        funnel=funnel,
        by_channel=by_channel,
        by_intent=by_intent,
        today_new=today_new,
        week_new=week_new,
    )


@router.get("/funnel")
async def dashboard_funnel(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    return await _get_dashboard_data(current_user.tenant_id, db)
