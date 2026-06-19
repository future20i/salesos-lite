"""AI-powered reply suggestion endpoint."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.auth import get_current_user
from src.models import Lead, Message, User, UserRole
from src.llm_client import suggest_reply

router = APIRouter(prefix="/api/suggest", tags=["suggest"])


# ── Schemas ───────────────────────────────────────────────────────

class SuggestReplyRequest(BaseModel):
    lead_id: str


class SuggestReplyResponse(BaseModel):
    suggestion: str


# ── Routes ────────────────────────────────────────────────────────

@router.post("/reply", response_model=SuggestReplyResponse)
async def suggest_reply_endpoint(
    body: SuggestReplyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate an AI-suggested reply for a lead based on the last 5 messages.

    JWT-protected with tenant isolation — the lead must belong to the
    current user's tenant.
    """
    # Validate lead_id
    try:
        lead_uuid = uuid.UUID(body.lead_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid lead_id format",
        )

    # Fetch lead — tenant isolation
    result = await db.execute(
        select(Lead).where(
            Lead.id == lead_uuid,
            Lead.tenant_id == current_user.tenant_id,
        )
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found",
        )

    # Reps can only access their assigned leads
    if current_user.role == UserRole.REP and lead.assigned_to != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lead not found",
        )

    # Fetch last 5 messages for the lead
    result = await db.execute(
        select(Message)
        .where(Message.lead_id == lead.id)
        .order_by(Message.created_at.desc())
        .limit(5)
    )
    messages = result.scalars().all()
    # Reverse to chronological order
    messages.reverse()

    # Format conversation context
    if not messages:
        context_parts = ["(No prior conversation — this is a new lead.)"]
    else:
        context_parts = []
        for m in messages:
            label = "Customer" if m.direction.value == "inbound" else "Rep"
            context_parts.append(f"{label}: {m.content}")

    context = "\n\n".join(context_parts)

    # Call LLM to generate suggestion
    suggestion = await suggest_reply(context)

    return SuggestReplyResponse(suggestion=suggestion)
