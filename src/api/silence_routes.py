"""Silence alert API — query, digest, trigger, acknowledge.

Silence alerts are FollowupEvent rows with kind='silence_alert'.
They're created by the background silence_check_loop (src/pipeline/__init__.py).
This module provides the read/acknowledge side for the SPA.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.auth import get_current_user
from src.models.user import User
from src.models.followup import FollowupEvent, FollowupItem
from src.models.opportunity import Opportunity, OpportunityStage

router = APIRouter(prefix="/api/ai", tags=["silence"])


# ── Schemas ────────────────────────────────────────────────────────────────

class SilenceAlertOut(BaseModel):
    event_id: int
    opportunity_id: str
    opportunity_name: str
    stage: str
    days_silent: int
    threshold: int
    last_inbound_at: str | None
    created_at: str
    acknowledged: bool = False


class SilenceDigestOut(BaseModel):
    unread_count: int
    alerts: list[SilenceAlertOut]


class SilenceCheckResult(BaseModel):
    alerts_generated: int
    message: str


# ── Helpers ────────────────────────────────────────────────────────────────

async def _query_alerts(
    db: AsyncSession, tenant_id, limit: int = 50, unread_only: bool = False,
    since: datetime | None = None,
) -> list[dict]:
    """Query silence alerts for a tenant, joined through followup_items → opportunity."""
    q = (
        select(FollowupEvent, FollowupItem, Opportunity)
        .join(FollowupItem, FollowupEvent.followup_id == FollowupItem.id)
        .join(Opportunity, FollowupItem.opportunity_id == Opportunity.id)
        .where(
            FollowupItem.tenant_id == tenant_id,
            FollowupEvent.kind == "silence_alert",
        )
        .order_by(FollowupEvent.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(q)
    rows = result.all()

    alerts = []
    for event, followup, opp in rows:
        payload = event.payload or {}
        created = event.created_at
        if since and created and created.replace(tzinfo=timezone.utc) <= since:
            continue
        alerts.append({
            "event_id": event.id,
            "opportunity_id": str(opp.id),
            "opportunity_name": opp.name,
            "stage": payload.get("stage", str(opp.stage.value if hasattr(opp.stage, 'value') else opp.stage)),
            "days_silent": payload.get("days_silent", 0),
            "threshold": payload.get("threshold", 14),
            "last_inbound_at": payload.get("last_inbound_at"),
            "created_at": created.isoformat() if created else None,
        })
    return alerts


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("/silence-alerts")
async def list_silence_alerts(
    limit: int = Query(50, ge=1, le=200),
    unread_only: bool = Query(True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SilenceAlertOut]:
    """List silence alerts for the current tenant.

    When unread_only=True (default), only returns alerts created after
    the user's last login. Set to False to see all alerts.
    """
    since = None
    if unread_only and current_user.last_login_at:
        since = current_user.last_login_at.replace(tzinfo=timezone.utc) if current_user.last_login_at.tzinfo is None else current_user.last_login_at

    alerts = await _query_alerts(db, current_user.tenant_id, limit=limit, since=since)
    return [SilenceAlertOut(**a) for a in alerts]


@router.get("/silence-digest")
async def silence_digest(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SilenceDigestOut:
    """Login-time digest: unread count + top 5 recent alerts.

    Called by the SPA after login to show a summary badge.
    Unread = alerts created after the user's last_login_at.
    """
    since = None
    if current_user.last_login_at:
        since = current_user.last_login_at.replace(tzinfo=timezone.utc) if current_user.last_login_at.tzinfo is None else current_user.last_login_at

    # Get all unread alerts (no limit for count)
    all_alerts = await _query_alerts(db, current_user.tenant_id, limit=200, since=since)
    top5 = all_alerts[:5]

    return SilenceDigestOut(
        unread_count=len(all_alerts),
        alerts=[SilenceAlertOut(**a) for a in top5],
    )


@router.post("/silence-check")
async def trigger_silence_check(
    current_user: User = Depends(get_current_user),
) -> SilenceCheckResult:
    """Manually trigger a silence check scan (sync, returns result).

    Note: this runs inline in the request — may take a few seconds for
    tenants with many opportunities. The background loop still runs hourly.
    """
    from src.pipeline import check_silent_opportunities
    count = await check_silent_opportunities()
    return SilenceCheckResult(
        alerts_generated=count,
        message=f"Scan complete. {count} new silence alert(s) generated." if count
        else "No new silence alerts — all opportunities have recent customer activity.",
    )


@router.post("/silence-alerts/{event_id}/acknowledge")
async def acknowledge_silence_alert(
    event_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Acknowledge/dismiss a silence alert. Marks it as seen by the current user.

    This updates the alert's payload with an acknowledged_at timestamp and
    the user ID so it won't appear in unread queries for this user.
    """
    result = await db.execute(
        select(FollowupEvent).where(FollowupEvent.id == event_id)
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    # Verify tenant access
    fu_result = await db.execute(
        select(FollowupItem).where(FollowupItem.id == event.followup_id)
    )
    followup = fu_result.scalar_one_or_none()
    if followup is None or followup.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Update payload with acknowledgement
    payload = dict(event.payload or {})
    payload["acknowledged_by"] = str(current_user.id)
    payload["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
    event.payload = payload
    await db.commit()

    return {"status": "ok", "event_id": event_id}
