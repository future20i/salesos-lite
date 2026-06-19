"""Phase 8 — Approval workflow API routes."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from src.database import get_db
from src.auth import get_current_user, require_role
from src.models import (
    Approval, ApprovalStatus, Lead, User, UserRole,
)

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


# ── Schemas ───────────────────────────────────────────────────────

class SubmitRequest(BaseModel):
    lead_id: str
    content: str


class RejectRequest(BaseModel):
    reason: str | None = None


class ApprovalItem(BaseModel):
    id: str
    lead_id: str
    customer_name: str
    submitted_by: str
    submitted_by_name: str
    status: str
    content: str
    reason: str | None
    created_at: str

    class Config:
        from_attributes = True


# ── Routes ────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def submit_approval(
    body: SubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit an AI-generated reply for manager approval.

    Any authenticated user can submit. The lead must exist in the
    user's tenant and the submitted content is stored for review.
    """
    # Resolve lead_id
    try:
        lead_uuid = uuid.UUID(body.lead_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid lead_id")

    # Verify lead exists and belongs to the user's tenant
    result = await db.execute(
        select(Lead).where(
            Lead.id == lead_uuid,
            Lead.tenant_id == current_user.tenant_id,
        )
    )
    lead = result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Create the approval record
    approval = Approval(
        tenant_id=current_user.tenant_id,
        lead_id=lead.id,
        submitted_by=current_user.id,
        status=ApprovalStatus.PENDING,
        content=body.content,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)

    return {
        "id": str(approval.id),
        "status": approval.status.value,
    }


@router.get("")
async def list_approvals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List pending approvals for the current user's tenant.

    Managers and admins see all approvals for the tenant.
    Reps see only their own submissions.
    """
    query = (
        select(Approval)
        .options(joinedload(Approval.lead))
        .where(Approval.tenant_id == current_user.tenant_id)
    )

    if current_user.role == UserRole.REP:
        query = query.where(Approval.submitted_by == current_user.id)

    query = query.order_by(Approval.created_at.desc())
    result = await db.execute(query)
    approvals = result.unique().scalars().all()

    items = []
    for a in approvals:
        # Get customer_name from lead relationship
        lead = a.lead if hasattr(a, 'lead') else None
        customer_name = lead.customer_name if lead else "Unknown"

        # Get submitted_by username
        result = await db.execute(
            select(User).where(User.id == a.submitted_by)
        )
        submitter = result.scalar_one_or_none()
        submitted_by_name = submitter.username if submitter else str(a.submitted_by)

        items.append(
            ApprovalItem(
                id=str(a.id),
                lead_id=str(a.lead_id),
                customer_name=customer_name,
                submitted_by=str(a.submitted_by),
                submitted_by_name=submitted_by_name,
                status=a.status.value,
                content=a.content or "",
                reason=a.reason,
                created_at=a.created_at.isoformat() if a.created_at else "",
            )
        )

    return items


@router.post("/{approval_id}/approve")
async def approve_approval(
    approval_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER)),
):
    """Approve a pending approval (manager/admin only)."""
    result = await db.execute(
        select(Approval).where(
            Approval.id == approval_id,
            Approval.tenant_id == current_user.tenant_id,
        )
    )
    approval = result.scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Approval is already {approval.status.value}",
        )

    approval.status = ApprovalStatus.APPROVED
    approval.reviewed_by = current_user.id
    approval.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(approval)

    return {
        "id": str(approval.id),
        "status": approval.status.value,
    }


@router.post("/{approval_id}/reject")
async def reject_approval(
    approval_id: uuid.UUID,
    body: RejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER)),
):
    """Reject a pending approval (manager/admin only)."""
    result = await db.execute(
        select(Approval).where(
            Approval.id == approval_id,
            Approval.tenant_id == current_user.tenant_id,
        )
    )
    approval = result.scalar_one_or_none()
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Approval is already {approval.status.value}",
        )

    approval.status = ApprovalStatus.REJECTED
    approval.reviewed_by = current_user.id
    approval.reason = body.reason
    approval.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(approval)

    return {
        "id": str(approval.id),
        "status": approval.status.value,
        "reason": approval.reason,
    }
