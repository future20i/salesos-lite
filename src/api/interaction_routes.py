"""InteractionLog CRUD routes — B2B sales relationship tracking.

Full CRUD for InteractionLog model:
  - List, detail, create interactions
  - Auto-capture from messages with LLM extraction
  - Timeline view with highlights
  - Tenant-isolated
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.auth import get_current_user
from src.models import InteractionLog, Message, Lead, PersonProfile, User
from src.llm_client import llm_complete

router = APIRouter(prefix="/api/interactions", tags=["interactions"])


# ═══════════════════════════════════════════════════════════════════════
#  Pydantic Schemas
# ═══════════════════════════════════════════════════════════════════════

class InteractionCreate(BaseModel):
    """Schema for logging a new interaction."""
    person_profile_id: uuid.UUID
    interaction_type: str  # message | call | visit | event | other
    channel: str | None = None
    summary: str | None = None
    personal_topics: list[str] | None = None
    key_takeaways: str | None = None
    tags: list[str] | None = None


class InteractionFromMessage(BaseModel):
    """Schema for auto-capturing interaction from a message."""
    message_id: uuid.UUID


class InteractionResponse(BaseModel):
    """Response schema for interaction log entries."""
    id: str
    person_profile_id: str
    tenant_id: str
    interaction_type: str
    channel: str | None = None
    summary: str | None = None
    personal_topics: list | None = None
    key_takeaways: str | None = None
    tags: list | None = None
    created_by: str | None = None
    created_at: str | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, obj: InteractionLog) -> "InteractionResponse":
        return cls(
            id=str(obj.id),
            person_profile_id=str(obj.person_profile_id),
            tenant_id=str(obj.tenant_id),
            interaction_type=obj.interaction_type,
            channel=obj.channel,
            summary=obj.summary,
            personal_topics=obj.personal_topics,
            key_takeaways=obj.key_takeaways,
            tags=obj.tags,
            created_by=str(obj.created_by) if obj.created_by else None,
            created_at=str(obj.created_at) if obj.created_at else None,
        )


class TimelineResponse(BaseModel):
    """Response schema for interaction timeline with highlights."""
    interactions: list[InteractionResponse]
    highlights: dict


# ═══════════════════════════════════════════════════════════════════════
#  Routes
# ═══════════════════════════════════════════════════════════════════════

@router.get("/")
async def list_interactions(
    person_profile_id: uuid.UUID | None = Query(None, description="Filter by person profile"),
    type: str | None = Query(None, description="Filter by interaction type"),
    limit: int = Query(50, ge=1, le=200, description="Max results to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[InteractionResponse]:
    """List interactions for the current tenant.

    Ordered by created_at DESC.
    """
    stmt = select(InteractionLog).where(
        InteractionLog.tenant_id == current_user.tenant_id
    )

    if person_profile_id is not None:
        stmt = stmt.where(InteractionLog.person_profile_id == person_profile_id)

    if type is not None:
        stmt = stmt.where(InteractionLog.interaction_type == type)

    stmt = stmt.order_by(InteractionLog.created_at.desc()).limit(limit)

    result = await db.execute(stmt)
    interactions = result.scalars().all()
    return [InteractionResponse.from_orm(i) for i in interactions]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_interaction(
    body: InteractionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InteractionResponse:
    """Log a new interaction. tenant_id and created_by are set automatically."""
    interaction = InteractionLog(
        person_profile_id=body.person_profile_id,
        tenant_id=current_user.tenant_id,
        interaction_type=body.interaction_type,
        channel=body.channel,
        summary=body.summary,
        personal_topics=body.personal_topics,
        key_takeaways=body.key_takeaways,
        tags=body.tags,
        created_by=current_user.id,
    )
    db.add(interaction)
    await db.commit()
    await db.refresh(interaction)

    return InteractionResponse.from_orm(interaction)


@router.get("/timeline/{person_profile_id}")
async def get_interaction_timeline(
    person_profile_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=500, description="Max results to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TimelineResponse:
    """Get interaction timeline for a person, ordered by created_at ASC.

    Includes highlights: first interaction, last interaction, and most recent
    personal topic.
    """
    stmt = (
        select(InteractionLog)
        .where(
            InteractionLog.person_profile_id == person_profile_id,
            InteractionLog.tenant_id == current_user.tenant_id,
        )
        .order_by(InteractionLog.created_at.asc())
        .limit(limit)
    )

    result = await db.execute(stmt)
    interactions = result.scalars().all()

    # Build highlights
    highlights = {}
    if interactions:
        first = interactions[0]
        last = interactions[-1]
        highlights["first_interaction"] = {
            "id": str(first.id),
            "type": first.interaction_type,
            "created_at": str(first.created_at) if first.created_at else None,
        }
        highlights["last_interaction"] = {
            "id": str(last.id),
            "type": last.interaction_type,
            "created_at": str(last.created_at) if last.created_at else None,
        }
        highlights["total_interactions"] = len(interactions)

        # Find most recent interaction that has personal_topics
        most_recent_topic = None
        for i in reversed(interactions):
            if i.personal_topics:
                most_recent_topic = i.personal_topics
                break
        highlights["most_recent_personal_topics"] = most_recent_topic

    return TimelineResponse(
        interactions=[InteractionResponse.from_orm(i) for i in interactions],
        highlights=highlights,
    )


@router.post("/from-message", status_code=status.HTTP_201_CREATED)
async def capture_from_message(
    body: InteractionFromMessage,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InteractionResponse:
    """Auto-capture an interaction from a message.

    Reads the message, finds or creates a PersonProfile for the lead,
    extracts personal_topics and key_takeaways via LLM, and creates
    an interaction log entry.
    """
    # 1. Read the message
    msg_result = await db.execute(
        select(Message).where(
            Message.id == body.message_id,
            Message.tenant_id == current_user.tenant_id,
        )
    )
    message = msg_result.scalar_one_or_none()

    if message is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    # 2. Find or create PersonProfile for the lead
    profile_result = await db.execute(
        select(PersonProfile).where(
            PersonProfile.lead_id == message.lead_id,
            PersonProfile.tenant_id == current_user.tenant_id,
        )
    )
    profile = profile_result.scalar_one_or_none()

    if profile is None:
        # Read lead to get customer_name for the profile
        lead_result = await db.execute(
            select(Lead).where(
                Lead.id == message.lead_id,
                Lead.tenant_id == current_user.tenant_id,
            )
        )
        lead = lead_result.scalar_one_or_none()

        profile = PersonProfile(
            tenant_id=current_user.tenant_id,
            lead_id=message.lead_id,
            full_name=lead.customer_name if lead else None,
            created_by=current_user.id,
        )
        db.add(profile)
        await db.flush()

    # 3. Auto-extract fields
    interaction_type = "message"
    channel = message.channel
    summary = message.content[:500] if message.content else None

    # 4. Use LLM to extract personal_topics and key_takeaways
    personal_topics = None
    key_takeaways = None

    if message.content:
        prompt = f"""Analyze the following message and extract personal/relationship information.

1. **personal_topics** — A JSON array of strings representing personal topics mentioned (e.g., ["family", "hobbies", "travel", "career", "sports"]). Include only topics that are directly mentioned or strongly implied. Return an empty array if no personal topics are found.

2. **key_takeaways** — 1-2 sentences in Chinese summarizing the key personal or relationship insight from this message. Focus on what a salesperson should remember for building rapport.

Respond ONLY with valid JSON. No markdown, no explanation.

Example response:
{{"personal_topics": ["travel", "family"], "key_takeaways": "客户提到下周要带家人去三亚度假，喜欢打高尔夫。"}}

Message:
{message.content[:3000]}"""

        try:
            llm_response = await llm_complete(
                prompt,
                system="You are a precise, concise analyst. Respond in Chinese with valid JSON only.",
            )
            # Parse the JSON from LLM response
            # Strip markdown fences if present
            cleaned = llm_response.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                cleaned = "\n".join(lines)
            parsed = json.loads(cleaned)
            personal_topics = parsed.get("personal_topics")
            key_takeaways = parsed.get("key_takeaways")
        except Exception:
            # LLM extraction is best-effort
            personal_topics = None
            key_takeaways = None

    # 5. Create interaction log
    interaction = InteractionLog(
        person_profile_id=profile.id,
        tenant_id=current_user.tenant_id,
        interaction_type=interaction_type,
        channel=channel,
        summary=summary,
        personal_topics=personal_topics,
        key_takeaways=key_takeaways,
        tags=["auto-captured"],
        created_by=current_user.id,
    )
    db.add(interaction)
    await db.commit()
    await db.refresh(interaction)

    return InteractionResponse.from_orm(interaction)


@router.get("/{interaction_id}")
async def get_interaction(
    interaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InteractionResponse:
    """Get a single interaction by ID. Tenant-scoped."""
    stmt = select(InteractionLog).where(
        InteractionLog.id == interaction_id,
        InteractionLog.tenant_id == current_user.tenant_id,
    )
    result = await db.execute(stmt)
    interaction = result.scalar_one_or_none()

    if interaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interaction not found",
        )

    return InteractionResponse.from_orm(interaction)
