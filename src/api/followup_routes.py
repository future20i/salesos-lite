"""FollowupItems — CRUD + state machine + AI draft trigger
AND Followup Rules API (auto follow-up engine).

Routers:
  items_router: /api/followups  — FollowupItem CRUD
  router:       /api/followup   — FollowupRule CRUD + engine (legacy, kept for app.py)
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.database import get_db
from src.auth import get_current_user
from src.models.user import User, UserRole
from src.models.followup import (
    FollowupItem,
    FollowupStatus,
    FollowupEvent,
    ReviewLevel,
)
from src.models.message import Message

# ═══════════════════════════════════════════════════════════════════════════════
# PART 1 — FollowupItem Schemas
# ═══════════════════════════════════════════════════════════════════════════════

class FollowupCreate(BaseModel):
    """Create a new followup item."""
    title: str
    opportunity_id: str
    body: str | None = None
    priority: int = 0
    source_type: str = "manual"
    source_id: str | None = None
    channel: str | None = None
    review_level: str = "commercial"
    assigned_to: str | None = None


class FollowupUpdate(BaseModel):
    """Update an existing followup item.  All fields optional."""
    title: str | None = None
    body: str | None = None
    priority: int | None = None
    review_level: str | None = None
    assigned_to: str | None = None


class FollowupEventOut(BaseModel):
    id: int
    kind: str
    payload: dict | None = None
    created_at: str | None = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj: FollowupEvent) -> "FollowupEventOut":
        return cls(
            id=obj.id,
            kind=obj.kind,
            payload=obj.payload,
            created_at=obj.created_at.isoformat() if obj.created_at else None,
        )


class FollowupResponse(BaseModel):
    id: str
    opportunity_id: str
    tenant_id: str
    title: str
    body: str | None = None
    status: str
    priority: int
    source_type: str
    source_id: str | None = None
    channel: str | None = None
    review_level: str
    ai_draft: str | None = None
    assigned_to: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    events: list[FollowupEventOut] = []

    class Config:
        from_attributes = True

    @classmethod
    def from_orm(cls, obj: FollowupItem) -> "FollowupResponse":
        return cls(
            id=str(obj.id),
            opportunity_id=str(obj.opportunity_id),
            tenant_id=str(obj.tenant_id),
            title=obj.title,
            body=obj.body,
            status=obj.status.value if isinstance(obj.status, FollowupStatus) else obj.status,
            priority=obj.priority,
            source_type=obj.source_type,
            source_id=str(obj.source_id) if obj.source_id else None,
            channel=obj.channel,
            review_level=obj.review_level.value if isinstance(obj.review_level, ReviewLevel) else obj.review_level,
            ai_draft=obj.ai_draft,
            assigned_to=str(obj.assigned_to) if obj.assigned_to else None,
            created_by=str(obj.created_by) if obj.created_by else None,
            created_at=obj.created_at.isoformat() if obj.created_at else None,
            started_at=obj.started_at.isoformat() if obj.started_at else None,
            completed_at=obj.completed_at.isoformat() if obj.completed_at else None,
            events=[FollowupEventOut.from_orm(e) for e in (obj.events or [])],
        )


class FollowupMoveRequest(BaseModel):
    to: str = Field(..., description="Target status: in_progress | pending_review | done")


class FollowupDraftResponse(BaseModel):
    draft: str


class FollowupReviewRequest(BaseModel):
    action: str = Field(..., description="approve | reject")


class FollowupFromMessageRequest(BaseModel):
    message_id: str
    opportunity_id: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# PART 2 — FollowupItem Endpoints
# ═══════════════════════════════════════════════════════════════════════════════

items_router = APIRouter(prefix="/api/followups", tags=["followups"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _add_event(
    db: AsyncSession,
    followup_id: uuid.UUID,
    kind: str,
    payload: dict | None = None,
) -> FollowupEvent:
    """Create and persist a FollowupEvent, return it."""
    event = FollowupEvent(
        followup_id=followup_id,
        kind=kind,
        payload=payload,
    )
    db.add(event)
    await db.flush()
    return event


async def _get_followup_or_404(
    db: AsyncSession,
    followup_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> FollowupItem:
    """Fetch a FollowupItem scoped to tenant, or raise 404."""
    result = await db.execute(
        select(FollowupItem)
        .options(joinedload(FollowupItem.events))
        .where(
            FollowupItem.id == followup_id,
            FollowupItem.tenant_id == tenant_id,
        )
    )
    item = result.unique().scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Followup item not found")
    return item


def _validate_status(allowed: set[str], current: str) -> None:
    if current not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot move from '{current}'. Allowed from: {allowed}",
        )


# ── GET /api/followups ──────────────────────────────────────────────────────

@items_router.get("")
async def list_followups(
    status: str | None = Query(None, description="Filter by status"),
    opportunity_id: str | None = Query(None, description="Filter by opportunity"),
    assigned_to: str | None = Query(None, description="Filter by assignee user id"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[FollowupResponse]:
    """List followup items for the current tenant.

    Reps see only followups assigned to them.
    Admins and managers see all followups in the tenant.
    """
    query = (
        select(FollowupItem)
        .options(joinedload(FollowupItem.events))
        .where(FollowupItem.tenant_id == current_user.tenant_id)
    )

    # RBAC: reps only see their own
    if current_user.role == UserRole.REP:
        query = query.where(FollowupItem.assigned_to == current_user.id)

    # Optional filters
    if status:
        try:
            st = FollowupStatus(status)
            query = query.where(FollowupItem.status == st)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    if opportunity_id:
        try:
            oid = uuid.UUID(opportunity_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid opportunity_id")
        query = query.where(FollowupItem.opportunity_id == oid)

    if assigned_to:
        try:
            auid = uuid.UUID(assigned_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid assigned_to")
        query = query.where(FollowupItem.assigned_to == auid)

    query = query.order_by(FollowupItem.created_at.desc())
    result = await db.execute(query)
    items = result.unique().scalars().all()

    return [FollowupResponse.from_orm(item) for item in items]


# ── GET /api/followups/{id} ──────────────────────────────────────────────────

@items_router.get("/{followup_id}")
async def get_followup(
    followup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowupResponse:
    """Get a single followup item with its events."""
    item = await _get_followup_or_404(db, followup_id, current_user.tenant_id)

    # RBAC: reps can only see items assigned to them
    if current_user.role == UserRole.REP and item.assigned_to != current_user.id:
        raise HTTPException(status_code=404, detail="Followup item not found")

    return FollowupResponse.from_orm(item)


# ── POST /api/followups ─────────────────────────────────────────────────────

@items_router.post("", status_code=status.HTTP_201_CREATED)
async def create_followup(
    body: FollowupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowupResponse:
    """Create a new followup item. Auto-sets tenant_id and records a 'created' event."""
    # Validate opportunity_id
    try:
        opp_id = uuid.UUID(body.opportunity_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid opportunity_id")

    # Validate review_level
    try:
        review_level = ReviewLevel(body.review_level)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid review_level '{body.review_level}'. Must be: routine, commercial, critical",
        )

    source_id = uuid.UUID(body.source_id) if body.source_id else None
    assigned_to = uuid.UUID(body.assigned_to) if body.assigned_to else None

    item = FollowupItem(
        tenant_id=current_user.tenant_id,
        opportunity_id=opp_id,
        title=body.title,
        body=body.body,
        status=FollowupStatus.TODO,
        priority=body.priority,
        source_type=body.source_type,
        source_id=source_id,
        channel=body.channel,
        review_level=review_level,
        assigned_to=assigned_to,
        created_by=current_user.id,
    )
    db.add(item)
    await db.flush()

    await _add_event(db, item.id, "created", {"by": str(current_user.id)})

    await db.commit()
    await db.refresh(item)

    # Reload with events
    return FollowupResponse.from_orm(
        await _get_followup_or_404(db, item.id, current_user.tenant_id)
    )


# ── PATCH /api/followups/{id} ───────────────────────────────────────────────

@items_router.patch("/{followup_id}")
async def update_followup(
    followup_id: uuid.UUID,
    body: FollowupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowupResponse:
    """Update fields on a followup item."""
    item = await _get_followup_or_404(db, followup_id, current_user.tenant_id)

    changed = False

    if body.title is not None:
        item.title = body.title
        changed = True
    if body.body is not None:
        item.body = body.body
        changed = True
    if body.priority is not None:
        item.priority = body.priority
        changed = True
    if body.review_level is not None:
        try:
            item.review_level = ReviewLevel(body.review_level)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid review_level '{body.review_level}'",
            )
        changed = True
    if body.assigned_to is not None:
        try:
            item.assigned_to = uuid.UUID(body.assigned_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid assigned_to")
        changed = True

    if changed:
        await _add_event(db, item.id, "updated", {
            "by": str(current_user.id),
            "fields": body.model_dump(exclude_none=True),
        })
        await db.commit()
        await db.refresh(item)

    return FollowupResponse.from_orm(item)


# ── POST /api/followups/{id}/move ───────────────────────────────────────────

VALID_MOVES: dict[str, list[str]] = {
    FollowupStatus.TODO.value: [
        FollowupStatus.IN_PROGRESS.value,
    ],
    FollowupStatus.IN_PROGRESS.value: [
        FollowupStatus.PENDING_REVIEW.value,
        FollowupStatus.DONE.value,
        FollowupStatus.TODO.value,
    ],
    FollowupStatus.PENDING_REVIEW.value: [
        FollowupStatus.DONE.value,
        FollowupStatus.IN_PROGRESS.value,
    ],
    FollowupStatus.DONE.value: [
        FollowupStatus.TODO.value,
        FollowupStatus.IN_PROGRESS.value,
    ],
}


@items_router.post("/{followup_id}/move")
async def move_followup(
    followup_id: uuid.UUID,
    body: FollowupMoveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowupResponse:
    """Move a followup item to a new status. Records an event and sets timestamps."""
    item = await _get_followup_or_404(db, followup_id, current_user.tenant_id)

    current_status = item.status.value if isinstance(item.status, FollowupStatus) else item.status
    target = body.to

    # Validate target value
    try:
        new_status = FollowupStatus(target)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{target}'. Must be: todo, in_progress, pending_review, done",
        )

    # Validate transition
    allowed = VALID_MOVES.get(current_status, [])
    if target not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot move from '{current_status}' to '{target}'. "
                   f"Allowed targets from '{current_status}': {allowed}",
        )

    now = datetime.now(timezone.utc)

    # Timestamp management
    old_status = current_status
    if target == FollowupStatus.IN_PROGRESS.value and item.started_at is None:
        item.started_at = now
    if target == FollowupStatus.DONE.value and item.completed_at is None:
        item.completed_at = now

    item.status = new_status

    await _add_event(db, item.id, "status_change", {
        "from": old_status,
        "to": target,
        "by": str(current_user.id),
    })

    await db.commit()
    await db.refresh(item)

    return FollowupResponse.from_orm(item)


# ── POST /api/followups/{id}/draft ──────────────────────────────────────────

async def _generate_followup_draft(item: FollowupItem) -> str:
    """Generate an AI draft for a followup item using the LLM client.

    Lazy-imports src.llm_client to avoid circular deps.
    Falls back gracefully if the function is unavailable.
    """
    try:
        from src.llm_client import suggest_reply

        context = f"Title: {item.title}\n"
        if item.body:
            context += f"Body: {item.body}\n"
        context += f"Priority: {item.priority}\n"
        context += f"Review level: {item.review_level.value if isinstance(item.review_level, ReviewLevel) else item.review_level}"

        draft = await suggest_reply(context)
        return draft
    except ImportError:
        return "(AI draft unavailable — LLM client not importable)"
    except Exception as exc:
        return f"(AI draft generation failed: {exc})"


@items_router.post("/{followup_id}/draft")
async def generate_draft(
    followup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowupDraftResponse:
    """Generate an AI draft for the followup item and store it in ai_draft."""
    item = await _get_followup_or_404(db, followup_id, current_user.tenant_id)

    draft = await _generate_followup_draft(item)
    item.ai_draft = draft

    await _add_event(db, item.id, "ai_draft_generated", {
        "by": str(current_user.id),
        "draft_length": len(draft),
    })

    await db.commit()
    await db.refresh(item)

    return FollowupDraftResponse(draft=item.ai_draft or "")


# ── POST /api/followups/{id}/review ─────────────────────────────────────────

@items_router.post("/{followup_id}/review")
async def review_followup(
    followup_id: uuid.UUID,
    body: FollowupReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowupResponse:
    """Approve or reject a followup item (manager/admin only).

    - approve → status = DONE, sets completed_at
    - reject  → status = IN_PROGRESS
    """
    if current_user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise HTTPException(status_code=403, detail="Only admins and managers can review")

    if body.action not in ("approve", "reject"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action '{body.action}'. Must be 'approve' or 'reject'",
        )

    item = await _get_followup_or_404(db, followup_id, current_user.tenant_id)

    now = datetime.now(timezone.utc)
    old_status = item.status.value if isinstance(item.status, FollowupStatus) else item.status

    if body.action == "approve":
        item.status = FollowupStatus.DONE
        if item.completed_at is None:
            item.completed_at = now
        await _add_event(db, item.id, "review_approved", {
            "by": str(current_user.id),
            "from": old_status,
        })
    else:  # reject
        item.status = FollowupStatus.IN_PROGRESS
        await _add_event(db, item.id, "review_rejected", {
            "by": str(current_user.id),
            "from": old_status,
        })

    await db.commit()
    await db.refresh(item)

    return FollowupResponse.from_orm(item)


# ── POST /api/followups/from-message ────────────────────────────────────────

@items_router.post("/from-message", status_code=status.HTTP_201_CREATED)
async def create_followup_from_message(
    body: FollowupFromMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FollowupResponse:
    """Create a FollowupItem from an existing message.

    Reads the Message, then creates a followup with source_type='conversation'
    and source_id pointing to the message.  If opportunity_id is not provided,
    the message's lead's first opportunity is used (if any).
    """
    # Validate message_id
    try:
        msg_id = uuid.UUID(body.message_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid message_id")

    # Fetch the message (tenant-scoped)
    result = await db.execute(
        select(Message).where(
            Message.id == msg_id,
            Message.tenant_id == current_user.tenant_id,
        )
    )
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    # Resolve opportunity_id
    if body.opportunity_id:
        try:
            opp_id = uuid.UUID(body.opportunity_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid opportunity_id")
    else:
        # Try to find an opportunity linked to the message's lead
        from src.models.opportunity import Opportunity
        opp_result = await db.execute(
            select(Opportunity.id)
            .where(
                Opportunity.tenant_id == current_user.tenant_id,
                Opportunity.lead_id == message.lead_id,
            )
            .order_by(Opportunity.created_at.desc())
            .limit(1)
        )
        opp_row = opp_result.scalar_one_or_none()
        if opp_row is None:
            raise HTTPException(
                status_code=400,
                detail="No opportunity found for this message's lead. Please provide opportunity_id.",
            )
        opp_id = opp_row

    # Build title from message preview
    preview = message.content[:100].replace("\n", " ") if message.content else "(no content)"
    title = f"Follow-up from message: {preview}"

    item = FollowupItem(
        tenant_id=current_user.tenant_id,
        opportunity_id=opp_id,
        title=title,
        body=message.content,
        status=FollowupStatus.TODO,
        source_type="conversation",
        source_id=message.id,
        channel=message.channel,
        created_by=current_user.id,
        assigned_to=current_user.id,
    )
    db.add(item)
    await db.flush()

    await _add_event(db, item.id, "created", {
        "by": str(current_user.id),
        "source": "from-message",
        "message_id": str(message.id),
    })

    await db.commit()
    await db.refresh(item)

    return FollowupResponse.from_orm(
        await _get_followup_or_404(db, item.id, current_user.tenant_id)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PART 3 — Existing Followup RULES routes (preserved for app.py compatibility)
# ═══════════════════════════════════════════════════════════════════════════════

# Re-imports needed by the rules engine
from datetime import timedelta

from sqlalchemy import update
from sqlalchemy import func as sa_func

from src.database import AsyncSessionLocal
from src.models.lead import Lead, LeadStatus, Intent, Channel
from src.models.message import Message, MessageDirection
from src.models.followup_rule import (
    FollowupRule,
    FollowupLog,
    TriggerType,
    ActionType,
)
from src.models.canned_response import CannedResponse, ResponseCategory
from httpx import AsyncClient

router = APIRouter(prefix="/api/followup", tags=["followup"])


# ── Rules Schemas ───────────────────────────────────────────────────────────

class FollowupRuleCreate(BaseModel):
    name: str
    trigger_type: str
    trigger_value: str
    action_type: str
    action_value: str
    enabled: bool = True


class FollowupRuleUpdate(BaseModel):
    name: str | None = None
    trigger_type: str | None = None
    trigger_value: str | None = None
    action_type: str | None = None
    action_value: str | None = None
    enabled: bool | None = None


class FollowupRuleOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    trigger_type: str
    trigger_value: str
    action_type: str
    action_value: str
    enabled: bool
    created_at: str | None = None

    @classmethod
    def from_orm(cls, obj: FollowupRule) -> "FollowupRuleOut":
        return cls(
            id=str(obj.id),
            tenant_id=str(obj.tenant_id),
            name=obj.name,
            trigger_type=obj.trigger_type.value if isinstance(obj.trigger_type, TriggerType) else obj.trigger_type,
            trigger_value=obj.trigger_value,
            action_type=obj.action_type.value if isinstance(obj.action_type, ActionType) else obj.action_type,
            action_value=obj.action_value,
            enabled=obj.enabled,
            created_at=str(obj.created_at) if obj.created_at else None,
        )


class FollowupLogOut(BaseModel):
    id: str
    rule_id: str
    tenant_id: str
    lead_id: str
    action_type: str
    action_value: str
    result: str | None = None
    success: bool
    created_at: str | None = None

    @classmethod
    def from_orm(cls, obj: FollowupLog) -> "FollowupLogOut":
        return cls(
            id=str(obj.id),
            rule_id=str(obj.rule_id),
            tenant_id=str(obj.tenant_id),
            lead_id=str(obj.lead_id),
            action_type=obj.action_type.value if isinstance(obj.action_type, ActionType) else obj.action_type,
            action_value=obj.action_value,
            result=obj.result,
            success=obj.success,
            created_at=str(obj.created_at) if obj.created_at else None,
        )


# ── Rules Routes ────────────────────────────────────────────────────────────

@router.get("/rules")
async def list_rules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FollowupRuleOut]:
    """List all follow-up rules for the current tenant."""
    result = await db.execute(
        select(FollowupRule)
        .where(FollowupRule.tenant_id == current_user.tenant_id)
        .order_by(FollowupRule.created_at.desc())
    )
    return [FollowupRuleOut.from_orm(item) for item in result.scalars().all()]


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: FollowupRuleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FollowupRuleOut:
    """Create a new follow-up rule for the current tenant."""
    try:
        trigger_type = TriggerType(body.trigger_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid trigger_type '{body.trigger_type}'. "
                   f"Must be one of: {[t.value for t in TriggerType]}",
        )
    try:
        action_type = ActionType(body.action_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid action_type '{body.action_type}'. "
                   f"Must be one of: {[a.value for a in ActionType]}",
        )

    rule = FollowupRule(
        tenant_id=current_user.tenant_id,
        name=body.name,
        trigger_type=trigger_type,
        trigger_value=body.trigger_value,
        action_type=action_type,
        action_value=body.action_value,
        enabled=body.enabled,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return FollowupRuleOut.from_orm(rule)


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: uuid.UUID,
    body: FollowupRuleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FollowupRuleOut:
    """Update an existing follow-up rule (tenant-scoped)."""
    result = await db.execute(
        select(FollowupRule).where(
            FollowupRule.id == rule_id,
            FollowupRule.tenant_id == current_user.tenant_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Follow-up rule not found",
        )

    if body.name is not None:
        rule.name = body.name
    if body.trigger_type is not None:
        try:
            rule.trigger_type = TriggerType(body.trigger_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid trigger_type '{body.trigger_type}'",
            )
    if body.trigger_value is not None:
        rule.trigger_value = body.trigger_value
    if body.action_type is not None:
        try:
            rule.action_type = ActionType(body.action_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid action_type '{body.action_type}'",
            )
    if body.action_value is not None:
        rule.action_value = body.action_value
    if body.enabled is not None:
        rule.enabled = body.enabled

    await db.commit()
    await db.refresh(rule)
    return FollowupRuleOut.from_orm(rule)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a follow-up rule (tenant-scoped)."""
    result = await db.execute(
        select(FollowupRule).where(
            FollowupRule.id == rule_id,
            FollowupRule.tenant_id == current_user.tenant_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Follow-up rule not found",
        )
    await db.delete(rule)
    await db.commit()


@router.get("/logs")
async def list_logs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
) -> list[FollowupLogOut]:
    """List recent follow-up execution logs for the current tenant."""
    result = await db.execute(
        select(FollowupLog)
        .where(FollowupLog.tenant_id == current_user.tenant_id)
        .order_by(FollowupLog.created_at.desc())
        .limit(limit)
    )
    return [FollowupLogOut.from_orm(item) for item in result.scalars().all()]


# ── Manual trigger (for testing) ────────────────────────────────────────────

@router.post("/run")
async def manual_run(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger rule evaluation for the current tenant."""
    logs = await evaluate_rules_for_tenant(db, current_user.tenant_id)
    return {"status": "ok", "rules_evaluated": len(logs)}


# ── Engine logic ────────────────────────────────────────────────────────────

async def evaluate_rules_for_tenant(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[FollowupLog]:
    """Evaluate all enabled follow-up rules for a single tenant.

    Returns the list of FollowupLog entries that were created.
    """
    result = await db.execute(
        select(FollowupRule).where(
            FollowupRule.tenant_id == tenant_id,
            FollowupRule.enabled == True,  # noqa: E712
        )
    )
    rules = result.scalars().all()

    now = datetime.now(timezone.utc)

    # Rate limit: skip if tenant hit daily cap
    todays_count = await _count_todays_actions(db, tenant_id)
    if todays_count >= DAILY_LIMIT_PER_TENANT:
        return []

    created_logs: list[FollowupLog] = []
    remaining = DAILY_LIMIT_PER_TENANT - todays_count

    for rule in rules:
        try:
            matching_leads = await _find_matching_leads(
                db, tenant_id, rule, now
            )
        except Exception:
            continue

        for lead in matching_leads:
            already_fired = await db.execute(
                select(FollowupLog).where(
                    FollowupLog.rule_id == rule.id,
                    FollowupLog.lead_id == lead.id,
                    FollowupLog.created_at
                    > now - timedelta(hours=24),
                ).limit(1)
            )
            if already_fired.scalar_one_or_none() is not None:
                continue

            try:
                result_text = await _execute_action(
                    db, lead, rule, now
                )
                success = True
            except Exception as exc:
                result_text = str(exc)
                success = False

            log = FollowupLog(
                rule_id=rule.id,
                tenant_id=tenant_id,
                lead_id=lead.id,
                action_type=rule.action_type,
                action_value=rule.action_value,
                result=result_text,
                success=success,
            )
            db.add(log)
            created_logs.append(log)
            remaining -= 1
            if remaining <= 0:
                break

    if created_logs:
        await db.commit()
        for log in created_logs:
            await db.refresh(log)

    return created_logs


async def _find_matching_leads(
    db: AsyncSession, tenant_id: uuid.UUID, rule: FollowupRule, now: datetime
) -> list[Lead]:
    """Return leads matching the given rule's trigger condition."""
    if rule.trigger_type == TriggerType.LEAD_INTENT:
        try:
            intent = Intent(rule.trigger_value)
        except ValueError:
            return []
        result = await db.execute(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.intent == intent,
                Lead.status != LeadStatus.CLOSED,
            )
        )
        return list(result.scalars().all())

    elif rule.trigger_type == TriggerType.TIME_SINCE_CONTACT:
        hours = _parse_hours(rule.trigger_value)
        if hours is None:
            return []
        cutoff = now - timedelta(hours=hours)

        latest_msg_subq = (
            select(
                Message.lead_id,
                sa_func.max(Message.created_at).label("last_contact"),
            )
            .where(Message.tenant_id == tenant_id)
            .group_by(Message.lead_id)
            .subquery()
        )

        result = await db.execute(
            select(Lead)
            .outerjoin(
                latest_msg_subq,
                Lead.id == latest_msg_subq.c.lead_id,
            )
            .where(
                Lead.tenant_id == tenant_id,
                Lead.status != LeadStatus.CLOSED,
                sa_func.coalesce(
                    latest_msg_subq.c.last_contact,
                    Lead.created_at,
                )
                < cutoff,
            )
        )
        return list(result.scalars().all())

    elif rule.trigger_type == TriggerType.TIME_SINCE_STATUS:
        hours = _parse_hours(rule.trigger_value)
        if hours is None:
            return []
        cutoff = now - timedelta(hours=hours)

        result = await db.execute(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.status != LeadStatus.CLOSED,
                Lead.last_activity_at < cutoff,
            )
        )
        return list(result.scalars().all())

    return []


async def _execute_action(
    db: AsyncSession, lead: Lead, rule: FollowupRule, now: datetime
) -> str:
    """Execute the action of a rule against a lead and return a result string."""
    from src.services.messaging import send_whatsapp_message, send_email_message

    if rule.action_type == ActionType.SEND_TEMPLATE:
        try:
            category = ResponseCategory(rule.action_value)
        except ValueError:
            category = None

        template_text = rule.action_value
        if category:
            tmpl_result = await db.execute(
                select(CannedResponse)
                .where(
                    CannedResponse.tenant_id == lead.tenant_id,
                    CannedResponse.category == category,
                )
                .limit(1)
            )
            template = tmpl_result.scalar_one_or_none()
            if template:
                template_text = template.content

        if lead.channel == Channel.WHATSAPP:
            msg_id = await send_whatsapp_message(db, lead, template_text)
            return f"WhatsApp sent (id={msg_id})" if msg_id else "WhatsApp send failed (not configured)"
        elif lead.channel == Channel.EMAIL:
            msg_id = await send_email_message(db, lead, template_text, subject="Follow-up")
            return f"Email sent (id={msg_id})" if msg_id else "Email send failed (no connection)"
        else:
            msg = Message(
                tenant_id=lead.tenant_id, lead_id=lead.id,
                content=template_text, direction=MessageDirection.OUTBOUND,
                sender="auto", channel=lead.channel,
            )
            db.add(msg)
            lead.last_activity_at = now
            return f"Template sent via {lead.channel.value}"

    elif rule.action_type == ActionType.SEND_AI_REPLY:
        ai_text = await _generate_ai_reply(db, lead, rule.action_value)
        if lead.channel == Channel.WHATSAPP:
            msg_id = await send_whatsapp_message(db, lead, ai_text)
            return f"AI reply sent via WhatsApp (id={msg_id})" if msg_id else "AI WhatsApp send failed"
        elif lead.channel == Channel.EMAIL:
            msg_id = await send_email_message(db, lead, ai_text, subject="Re: Your inquiry")
            return f"AI reply sent via Email (id={msg_id})" if msg_id else "AI Email send failed"
        else:
            msg = Message(
                tenant_id=lead.tenant_id, lead_id=lead.id,
                content=ai_text, direction=MessageDirection.OUTBOUND,
                sender="auto", channel=lead.channel,
            )
            db.add(msg)
            lead.last_activity_at = now
            return f"AI reply sent via {lead.channel.value}"

    elif rule.action_type == ActionType.ASSIGN_TO:
        lead.assigned_to = uuid.UUID(rule.action_value) if rule.action_value else None
        return f"Assigned lead {lead.id} to user {rule.action_value}"

    elif rule.action_type == ActionType.SEND_WEBHOOK:
        try:
            async with AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    rule.action_value,
                    json={
                        "event": "followup_triggered",
                        "lead_id": str(lead.id),
                        "lead_name": lead.customer_name,
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "tenant_id": str(lead.tenant_id),
                        "timestamp": now.isoformat(),
                    },
                )
            return f"Webhook POST → {rule.action_value} (status={resp.status_code})"
        except Exception as exc:
            return f"Webhook failed: {exc}"

    return f"Unknown action type: {rule.action_type}"


def _parse_hours(value: str) -> int | None:
    """Parse strings like '48h', '72h', '168h' into hours as int."""
    value = value.strip().lower()
    if value.endswith("h"):
        try:
            return int(value[:-1])
        except ValueError:
            return None
    try:
        return int(value)
    except ValueError:
        return None


async def _generate_ai_reply(
    db: AsyncSession, lead: Lead, prompt_hint: str
) -> str:
    """Generate an AI reply for a lead based on recent conversation context."""
    recent_result = await db.execute(
        select(Message)
        .where(Message.lead_id == lead.id)
        .order_by(Message.created_at.desc())
        .limit(10)
    )
    recent_msgs = list(recent_result.scalars().all())
    recent_msgs.reverse()

    context_lines = []
    for m in recent_msgs:
        prefix = "Customer" if m.direction == MessageDirection.INBOUND else "Agent"
        context_lines.append(f"{prefix}: {m.content[:500]}")

    context = "\n".join(context_lines) if context_lines else f"Customer: {lead.customer_name}\n(no messages yet)"

    try:
        from src.llm_client import suggest_reply
        return await suggest_reply(context)
    except Exception:
        return (
            f"Hi {lead.customer_name}, just checking in — "
            "is there anything I can help with regarding your inquiry? "
            "Feel free to reach out anytime!"
        )


# ── Rate limiting ───────────────────────────────────────────────────────────

DAILY_LIMIT_PER_TENANT = 20


async def _count_todays_actions(
    db: AsyncSession, tenant_id: uuid.UUID
) -> int:
    """Count followup actions executed today for a tenant."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    result = await db.execute(
        select(sa_func.count(FollowupLog.id)).where(
            FollowupLog.tenant_id == tenant_id,
            FollowupLog.created_at >= today_start,
        )
    )
    return result.scalar() or 0


# ── Seed defaults ───────────────────────────────────────────────────────────

SEED_RULES: list[dict] = [
    {
        "name": "48h no reply → send revival template",
        "trigger_type": TriggerType.TIME_SINCE_CONTACT,
        "trigger_value": "48h",
        "action_type": ActionType.SEND_TEMPLATE,
        "action_value": ResponseCategory.REVIVAL.value,
    },
    {
        "name": "Hot lead → assign to manager",
        "trigger_type": TriggerType.LEAD_INTENT,
        "trigger_value": "hot",
        "action_type": ActionType.ASSIGN_TO,
        "action_value": "",
    },
    {
        "name": "7d no activity → send order nudge",
        "trigger_type": TriggerType.TIME_SINCE_CONTACT,
        "trigger_value": "168h",
        "action_type": ActionType.SEND_TEMPLATE,
        "action_value": ResponseCategory.ORDER_NUDGE.value,
    },
]


async def seed_default_rules(db: AsyncSession) -> None:
    """Seed 3 default follow-up rules for all tenants that have none yet."""
    from src.models.tenant import Tenant

    tenant_result = await db.execute(select(Tenant))
    tenants = tenant_result.scalars().all()

    for tenant in tenants:
        existing = await db.execute(
            select(FollowupRule)
            .where(FollowupRule.tenant_id == tenant.id)
            .limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            continue

        for rule_data in SEED_RULES:
            rule = FollowupRule(
                tenant_id=tenant.id,
                name=rule_data["name"],
                trigger_type=rule_data["trigger_type"],
                trigger_value=rule_data["trigger_value"],
                action_type=rule_data["action_type"],
                action_value=rule_data["action_value"],
                enabled=True,
            )
            db.add(rule)

    await db.commit()


async def followup_evaluation_loop(interval_seconds: int = 60) -> None:
    """Background loop: evaluate follow-up rules for all tenants periodically."""
    import asyncio, logging
    _log = logging.getLogger(__name__)
    while True:
        try:
            async with AsyncSessionLocal() as _db:
                from src.models.tenant import Tenant
                result = await _db.execute(select(Tenant))
                tenants = result.scalars().all()
                total = 0
                for t in tenants:
                    logs = await evaluate_rules_for_tenant(_db, t.id)
                    total += len(logs)
                if total:
                    _log.info("Followup: executed %d actions across %d tenants", total, len(tenants))
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("Followup evaluation loop error")
        await asyncio.sleep(interval_seconds)
