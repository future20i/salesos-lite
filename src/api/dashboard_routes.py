"""Dashboard API — conversion funnel, lead stats, team performance."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.lead import Lead, LeadStatus, Intent
from src.models.message import Message, MessageDirection
from src.models.approval import Approval, ApprovalStatus
from src.models.user import User, UserRole
from src.auth import get_current_user, require_role

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


# ── Productivity endpoint ────────────────────────────────────────────────


class ProductivityItem(BaseModel):
    user_id: str
    username: str
    leads_handled: int
    messages_sent: int
    avg_response_time_minutes: float | None
    approval_rate: float | None  # 0.0–1.0


@router.get("/productivity")
async def dashboard_productivity(
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER)),
    db: AsyncSession = Depends(get_db),
) -> list[ProductivityItem]:
    """Per-rep productivity stats for the current tenant."""
    tenant_id = current_user.tenant_id

    # 1. All REP users in the tenant
    result = await db.execute(
        select(User).where(
            User.tenant_id == tenant_id,
            User.role == UserRole.REP,
        )
    )
    reps = result.scalars().all()

    items: list[ProductivityItem] = []
    for rep in reps:
        # leads_handled: count of leads assigned to this rep
        result = await db.execute(
            select(func.count(Lead.id)).where(
                Lead.tenant_id == tenant_id,
                Lead.assigned_to == rep.id,
            )
        )
        leads_handled = result.scalar() or 0

        # messages_sent: count of outbound messages where sender == rep.username
        result = await db.execute(
            select(func.count(Message.id)).where(
                Message.tenant_id == tenant_id,
                Message.sender == rep.username,
                Message.direction == MessageDirection.OUTBOUND,
            )
        )
        messages_sent = result.scalar() or 0

        # avg_response_time: average time (minutes) between a lead's creation
        # and the first outbound message sent by this rep on leads they own.
        # Simplified: avg of (first_outbound.created_at - lead.created_at)
        # for leads assigned to rep where there is at least one outbound message
        # from that rep on the lead.
        avg_response_time: float | None = None
        # Get leads assigned to this rep
        lead_result = await db.execute(
            select(Lead.id, Lead.created_at).where(
                Lead.tenant_id == tenant_id,
                Lead.assigned_to == rep.id,
            )
        )
        assigned_leads = lead_result.all()
        response_diffs: list[float] = []
        for lead_id, lead_created in assigned_leads:
            # Find the earliest outbound message from this rep on this lead
            msg_result = await db.execute(
                select(Message.created_at)
                .where(
                    Message.tenant_id == tenant_id,
                    Message.lead_id == lead_id,
                    Message.sender == rep.username,
                    Message.direction == MessageDirection.OUTBOUND,
                )
                .order_by(Message.created_at.asc())
                .limit(1)
            )
            first_out = msg_result.scalar_one_or_none()
            if first_out is not None and lead_created is not None:
                diff = (first_out - lead_created).total_seconds() / 60.0
                if diff >= 0:
                    response_diffs.append(diff)
        if response_diffs:
            avg_response_time = round(sum(response_diffs) / len(response_diffs), 2)

        # approval_rate: count of approved / total approvals submitted by rep
        result = await db.execute(
            select(
                func.count(Approval.id).filter(
                    Approval.status == ApprovalStatus.APPROVED
                ),
                func.count(Approval.id),
            ).where(
                Approval.tenant_id == tenant_id,
                Approval.submitted_by == rep.id,
            )
        )
        approved_count, total_count = result.one()
        approval_rate: float | None = (
            round(approved_count / total_count, 4) if total_count > 0 else None
        )

        items.append(
            ProductivityItem(
                user_id=str(rep.id),
                username=rep.username,
                leads_handled=leads_handled,
                messages_sent=messages_sent,
                avg_response_time_minutes=avg_response_time,
                approval_rate=approval_rate,
            )
        )

    return items
