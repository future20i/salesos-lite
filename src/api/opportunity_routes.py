"""Opportunity CRUD routes — B2B sales pipeline management.

Full CRUD for Opportunity model:
  - List, detail, create, update (with stage-transition rules), delete (guarded)
  - Tenant-isolated, RBAC (REP sees only assigned)
  - Stage transitions: WON/LOST/SHELVED are terminal
  - On WON → related Lead set to CLOSED
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_db
from src.auth import get_current_user, require_role
from src.models import (
    Opportunity,
    OpportunityStage,
    Lead,
    LeadStatus,
    User,
    UserRole,
    FollowupItem,
    FollowupStatus,
)

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])

# ── Terminal stages (cannot transition away from) ────────────────────
_TERMINAL = {OpportunityStage.WON, OpportunityStage.LOST, OpportunityStage.SHELVED}

# ── Followup statuses considered "active" (block deletion) ───────────
_ACTIVE_FOLLOWUP = {FollowupStatus.TODO, FollowupStatus.IN_PROGRESS, FollowupStatus.PENDING_REVIEW}


# ═══════════════════════════════════════════════════════════════════════
#  Pydantic Schemas
# ═══════════════════════════════════════════════════════════════════════

class OpportunityCreate(BaseModel):
    """Schema for creating a new opportunity."""
    name: str
    lead_id: uuid.UUID | None = None
    value: float | None = None
    probability: int | None = None
    stage: OpportunityStage = OpportunityStage.LEAD_VALIDATION
    expected_close_date: datetime | None = None
    assigned_to: uuid.UUID | None = None
    decision_chain: dict | None = None
    competitor_tracking: dict | None = None
    notes: str | None = None


class OpportunityUpdate(BaseModel):
    """Schema for patching an existing opportunity. All fields optional."""
    name: str | None = None
    lead_id: uuid.UUID | None = None
    value: float | None = None
    probability: int | None = None
    stage: OpportunityStage | None = None
    expected_close_date: datetime | None = None
    assigned_to: uuid.UUID | None = None
    decision_chain: dict | None = None
    competitor_tracking: dict | None = None
    notes: str | None = None


class OpportunityResponse(BaseModel):
    """Response schema — includes lead customer_name via join."""
    id: str
    tenant_id: str
    lead_id: str | None = None
    lead_customer_name: str | None = None
    name: str
    value: float | None = None
    probability: int | None = None
    stage: str
    expected_close_date: str | None = None
    assigned_to: str | None = None
    decision_chain: dict | None = None
    competitor_tracking: dict | None = None
    notes: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    followup_count: int | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, obj: Opportunity, followup_count: int | None = None) -> "OpportunityResponse":
        lead_customer_name: str | None = None
        if hasattr(obj, "lead") and obj.lead is not None:
            lead_customer_name = obj.lead.customer_name

        return cls(
            id=str(obj.id),
            tenant_id=str(obj.tenant_id),
            lead_id=str(obj.lead_id) if obj.lead_id else None,
            lead_customer_name=lead_customer_name,
            name=obj.name,
            value=obj.value,
            probability=obj.probability,
            stage=obj.stage.value if isinstance(obj.stage, OpportunityStage) else obj.stage,
            expected_close_date=str(obj.expected_close_date) if obj.expected_close_date else None,
            assigned_to=str(obj.assigned_to) if obj.assigned_to else None,
            decision_chain=obj.decision_chain,
            competitor_tracking=obj.competitor_tracking,
            notes=obj.notes,
            created_by=str(obj.created_by) if obj.created_by else None,
            created_at=str(obj.created_at) if obj.created_at else None,
            updated_at=str(obj.updated_at) if obj.updated_at else None,
            followup_count=followup_count,
        )


# ═══════════════════════════════════════════════════════════════════════
#  Routes
# ═══════════════════════════════════════════════════════════════════════

@router.get("/")
async def list_opportunities(
    stage: str | None = Query(None, description="Filter by opportunity stage"),
    assigned_to: uuid.UUID | None = Query(None, description="Filter by assigned user"),
    q: str | None = Query(None, description="Search by opportunity name (case-insensitive)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OpportunityResponse]:
    """List opportunities for the current tenant.

    REP users see only opportunities assigned to them.
    ADMIN/MANAGER users see all tenant opportunities.
    """
    stmt = (
        select(Opportunity)
        .options(selectinload(Opportunity.lead))
        .where(Opportunity.tenant_id == current_user.tenant_id)
    )

    # RBAC: rep sees only their own
    if current_user.role == UserRole.REP:
        stmt = stmt.where(Opportunity.assigned_to == current_user.id)

    # Filters
    if stage is not None:
        try:
            stage_enum = OpportunityStage(stage)
        except ValueError:
            valid = [s.value for s in OpportunityStage]
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid stage '{stage}'. Must be one of: {valid}",
            )
        stmt = stmt.where(Opportunity.stage == stage_enum)

    if assigned_to is not None:
        stmt = stmt.where(Opportunity.assigned_to == assigned_to)

    if q is not None:
        stmt = stmt.where(Opportunity.name.ilike(f"%{q}%"))

    stmt = stmt.order_by(Opportunity.updated_at.desc())

    result = await db.execute(stmt)
    opportunities = result.unique().scalars().all()
    return [OpportunityResponse.from_orm(o) for o in opportunities]


@router.get("/{opportunity_id}")
async def get_opportunity(
    opportunity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OpportunityResponse:
    """Get a single opportunity with followup count."""
    stmt = (
        select(Opportunity)
        .options(selectinload(Opportunity.lead))
        .where(
            Opportunity.id == opportunity_id,
            Opportunity.tenant_id == current_user.tenant_id,
        )
    )
    result = await db.execute(stmt)
    opp = result.unique().scalar_one_or_none()

    if opp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Opportunity not found",
        )

    # RBAC: rep can only see their own
    if current_user.role == UserRole.REP and opp.assigned_to != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Opportunity not found",
        )

    # Count followups (all statuses)
    count_result = await db.execute(
        select(func.count(FollowupItem.id)).where(
            FollowupItem.opportunity_id == opportunity_id,
            FollowupItem.tenant_id == current_user.tenant_id,
        )
    )
    followup_count = count_result.scalar() or 0

    return OpportunityResponse.from_orm(opp, followup_count=followup_count)


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_opportunity(
    body: OpportunityCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OpportunityResponse:
    """Create a new opportunity. tenant_id and created_by are set automatically."""
    opp = Opportunity(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        name=body.name,
        lead_id=body.lead_id,
        value=body.value,
        probability=body.probability,
        stage=body.stage,
        expected_close_date=body.expected_close_date,
        assigned_to=body.assigned_to,
        decision_chain=body.decision_chain,
        competitor_tracking=body.competitor_tracking,
        notes=body.notes,
    )
    db.add(opp)
    await db.commit()

    # Reload with lead relationship for response
    stmt = (
        select(Opportunity)
        .options(selectinload(Opportunity.lead))
        .where(Opportunity.id == opp.id)
    )
    result = await db.execute(stmt)
    opp = result.unique().scalar_one()

    return OpportunityResponse.from_orm(opp)


@router.patch("/{opportunity_id}")
async def update_opportunity(
    opportunity_id: uuid.UUID,
    body: OpportunityUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OpportunityResponse:
    """Update an opportunity.

    Enforces stage-transition rules:
    - WON, LOST, SHELVED are terminal — cannot be changed to another stage.
    - When stage is changed to WON, the related Lead (if any) is set to CLOSED.
    """
    stmt = (
        select(Opportunity)
        .options(selectinload(Opportunity.lead))
        .where(
            Opportunity.id == opportunity_id,
            Opportunity.tenant_id == current_user.tenant_id,
        )
    )
    result = await db.execute(stmt)
    opp = result.unique().scalar_one_or_none()

    if opp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Opportunity not found",
        )

    # ── Stage-transition validation ──────────────────────────────────
    if body.stage is not None and body.stage != opp.stage:
        if opp.stage in _TERMINAL:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot change stage from terminal stage "
                    f"'{opp.stage.value}'. Terminal stages are final."
                ),
            )

    # ── Apply updates ────────────────────────────────────────────────
    if body.name is not None:
        opp.name = body.name
    if body.lead_id is not None:
        opp.lead_id = body.lead_id
    if body.value is not None:
        opp.value = body.value
    if body.probability is not None:
        opp.probability = body.probability
    if body.stage is not None:
        opp.stage = body.stage
    if body.expected_close_date is not None:
        opp.expected_close_date = body.expected_close_date
    if body.assigned_to is not None:
        opp.assigned_to = body.assigned_to
    if body.decision_chain is not None:
        opp.decision_chain = body.decision_chain
    if body.competitor_tracking is not None:
        opp.competitor_tracking = body.competitor_tracking
    if body.notes is not None:
        opp.notes = body.notes

    # ── On WON → close related Lead ────────────────────────────────
    if body.stage == OpportunityStage.WON and opp.lead_id is not None:
        lead_result = await db.execute(
            select(Lead).where(Lead.id == opp.lead_id)
        )
        lead = lead_result.scalar_one_or_none()
        if lead is not None and lead.status != LeadStatus.CLOSED:
            lead.status = LeadStatus.CLOSED

    await db.commit()
    await db.refresh(opp)

    # Reload with lead for response
    stmt = (
        select(Opportunity)
        .options(selectinload(Opportunity.lead))
        .where(Opportunity.id == opp.id)
    )
    result = await db.execute(stmt)
    opp = result.unique().scalar_one()

    return OpportunityResponse.from_orm(opp)


@router.delete("/{opportunity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_opportunity(
    opportunity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete an opportunity.

    Only allowed when:
    - Stage is LOST or SHELVED
    - No active followups exist (TODO, IN_PROGRESS, or PENDING_REVIEW)
    """
    stmt = select(Opportunity).where(
        Opportunity.id == opportunity_id,
        Opportunity.tenant_id == current_user.tenant_id,
    )
    result = await db.execute(stmt)
    opp = result.scalar_one_or_none()

    if opp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Opportunity not found",
        )

    # 1. Must be LOST or SHELVED
    if opp.stage not in (OpportunityStage.LOST, OpportunityStage.SHELVED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Can only delete opportunities in LOST or SHELVED stage",
        )

    # 2. No active followups
    active_result = await db.execute(
        select(func.count(FollowupItem.id)).where(
            FollowupItem.opportunity_id == opportunity_id,
            FollowupItem.status.in_(_ACTIVE_FOLLOWUP),
        )
    )
    active_count = active_result.scalar() or 0
    if active_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete opportunity with {active_count} active followup(s)",
        )

    await db.delete(opp)
    await db.commit()
