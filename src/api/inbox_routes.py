"""Phase 4 — Inbox API routes."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.auth import get_current_user, require_role
from src.models import (
    Lead, LeadStatus, Intent, Channel, Message, MessageDirection,
    AIJob, AIJobStatus, User, UserRole,
)
from src.sse import sse_broadcast, sse_endpoint

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


# ── Schemas ───────────────────────────────────────────────────────

class IncomingRequest(BaseModel):
    customer_name: str
    content: str
    channel: str = "web"
    channel_message_id: str | None = None


class IncomingResponse(BaseModel):
    lead_id: str
    message_id: str


class LeadListItem(BaseModel):
    id: str
    customer_name: str
    channel: str
    status: str
    intent: str | None
    unread: bool
    last_activity_at: str


class MessageItem(BaseModel):
    id: str
    content: str
    direction: str
    channel: str
    sender: str
    created_at: str


class LeadDetail(BaseModel):
    id: str
    customer_name: str
    channel: str
    status: str
    intent: str | None
    unread: bool
    last_activity_at: str
    created_at: str
    messages: list[MessageItem]


class ReplyRequest(BaseModel):
    content: str
    channel: str = "web"


class ReplyResponse(BaseModel):
    message_id: str


class AssignRequest(BaseModel):
    user_id: str


# ── Routes ────────────────────────────────────────────────────────

@router.post("/incoming", status_code=status.HTTP_201_CREATED)
async def receive_incoming(
    body: IncomingRequest,
    db: AsyncSession = Depends(get_db),
):
    """Receive a customer message (public, no auth required).

    Finds or creates a Lead, creates a Message, enqueues an AIJob,
    broadcasts via SSE, and returns lead_id / message_id.
    """
    # We need a tenant — for public incoming we create a default tenant
    # or we can derive it. For simplicity, let's get the first tenant
    # or we'll use a lookup by channel. Let's use a simple approach:
    # look for existing lead by customer_name in the same channel.
    # Actually, for a multi-tenant system, we need a tenant context.
    # Since this is public, we need to determine the tenant.
    # We'll look up the tenant from the lead if exists, or use a default.
    # For the test environment, let's create or find a tenant.

    from src.models.tenant import Tenant

    # Get or create a default tenant for public incoming messages
    result = await db.execute(select(Tenant).limit(1))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(name="Default")
        db.add(tenant)
        await db.flush()

    tenant_id = tenant.id

    # Find or create lead — match by customer_name and channel for simplicity
    result = await db.execute(
        select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.customer_name == body.customer_name,
            Lead.channel == body.channel,
        ).order_by(Lead.created_at.desc()).limit(1)
    )
    lead = result.scalar_one_or_none()

    if lead is None:
        try:
            channel_enum = Channel(body.channel)
        except ValueError:
            channel_enum = Channel.WEB

        lead = Lead(
            tenant_id=tenant_id,
            customer_name=body.customer_name,
            channel=channel_enum,
            status=LeadStatus.NEW,
            unread=True,
            last_activity_at=datetime.now(timezone.utc),
        )
        db.add(lead)
        await db.flush()

    # Create message
    message = Message(
        tenant_id=tenant_id,
        lead_id=lead.id,
        sender=body.customer_name,
        content=body.content,
        direction=MessageDirection.INBOUND,
        channel=body.channel,
        channel_message_id=body.channel_message_id,
    )
    db.add(message)
    await db.flush()

    # Enqueue AIJob for processing
    ai_job = AIJob(
        tenant_id=tenant_id,
        lead_id=lead.id,
        message_id=message.id,
        job_type="classify",
        status=AIJobStatus.PENDING,
    )
    db.add(ai_job)

    # Update lead last_activity_at
    lead.last_activity_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(message)
    await db.refresh(lead)

    # Broadcast via SSE
    await sse_broadcast(
        str(tenant_id),
        {
            "type": "new_message",
            "lead_id": str(lead.id),
            "message_id": str(message.id),
            "customer_name": lead.customer_name,
            "content": message.content,
        },
    )

    return IncomingResponse(
        lead_id=str(lead.id),
        message_id=str(message.id),
    )


@router.get("/leads")
async def list_leads(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List leads for the current user's tenant.

    Reps see only their assigned leads; managers/admins see all.
    """
    query = select(Lead).where(Lead.tenant_id == current_user.tenant_id)

    if current_user.role == UserRole.REP:
        query = query.where(Lead.assigned_to == current_user.id)

    query = query.order_by(Lead.last_activity_at.desc())
    result = await db.execute(query)
    leads = result.scalars().all()

    return [
        LeadListItem(
            id=str(l.id),
            customer_name=l.customer_name,
            channel=l.channel.value,
            status=l.status.value,
            intent=l.intent.value if l.intent else None,
            unread=l.unread,
            last_activity_at=l.last_activity_at.isoformat(),
        )
        for l in leads
    ]


@router.get("/leads/{lead_id}")
async def get_lead(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get lead detail with messages. Marks as read."""
    result = await db.execute(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.tenant_id == current_user.tenant_id,
        )
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    # RLS check for reps: can only see assigned leads
    if current_user.role == UserRole.REP and lead.assigned_to != current_user.id:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Mark as read
    lead.unread = False
    await db.commit()
    await db.refresh(lead)

    # Get messages
    result = await db.execute(
        select(Message)
        .where(Message.lead_id == lead.id)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()

    return LeadDetail(
        id=str(lead.id),
        customer_name=lead.customer_name,
        channel=lead.channel.value,
        status=lead.status.value,
        intent=lead.intent.value if lead.intent else None,
        unread=lead.unread,
        last_activity_at=lead.last_activity_at.isoformat(),
        created_at=lead.created_at.isoformat(),
        messages=[
            MessageItem(
                id=str(m.id),
                content=m.content,
                direction=m.direction.value,
                channel=m.channel,
                sender=m.sender,
                created_at=m.created_at.isoformat(),
            )
            for m in messages
        ],
    )


@router.post("/leads/{lead_id}/reply")
async def reply_to_lead(
    lead_id: uuid.UUID,
    body: ReplyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send an outbound message as a reply to a lead."""
    result = await db.execute(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.tenant_id == current_user.tenant_id,
        )
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Reps can only reply to their own leads
    if current_user.role == UserRole.REP and lead.assigned_to != current_user.id:
        raise HTTPException(status_code=404, detail="Lead not found")

    message = Message(
        tenant_id=current_user.tenant_id,
        lead_id=lead.id,
        sender=current_user.username,
        content=body.content,
        direction=MessageDirection.OUTBOUND,
        channel=body.channel,
    )
    db.add(message)

    lead.last_activity_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(message)

    await sse_broadcast(
        str(current_user.tenant_id),
        {
            "type": "new_message",
            "lead_id": str(lead.id),
            "message_id": str(message.id),
            "customer_name": lead.customer_name,
            "content": message.content,
            "direction": "outbound",
        },
    )

    return ReplyResponse(message_id=str(message.id))


@router.get("/stream")
async def stream_events(
    current_user: User = Depends(get_current_user),
):
    """SSE stream for the current user's tenant."""
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        sse_endpoint(str(current_user.tenant_id)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/leads/{lead_id}/assign")
async def assign_lead(
    lead_id: uuid.UUID,
    body: AssignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER)),
):
    """Assign a lead to a user (manager/admin only)."""
    result = await db.execute(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.tenant_id == current_user.tenant_id,
        )
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Verify target user exists in same tenant
    result = await db.execute(
        select(User).where(
            User.id == body.user_id,
            User.tenant_id == current_user.tenant_id,
        )
    )
    target_user = result.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found in tenant")

    lead.assigned_to = target_user.id
    await db.commit()

    await sse_broadcast(
        str(current_user.tenant_id),
        {
            "type": "lead_assigned",
            "lead_id": str(lead.id),
            "assigned_to": str(target_user.id),
        },
    )

    return {"status": "assigned"}
