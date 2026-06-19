from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from models import Approval, ApprovalStatus, Conversation, User, UserRole
from database import get_db
from auth import get_current_user, require_role

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


# ── Schemas ────────────────────────────────────────────────────────

class SubmitRequest(BaseModel):
    conversation_id: int
    reason: str | None = None


class ActionRequest(BaseModel):
    action: str = Field(..., pattern="^(approve|reject)$")
    comment: str | None = None


# ── Routes ─────────────────────────────────────────────────────────

@router.post("/submit")
def submit_approval(
    body: SubmitRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = db.get(Conversation, body.conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check no existing pending
    existing = db.execute(
        select(Approval).where(
            Approval.conversation_id == body.conversation_id,
            Approval.status == ApprovalStatus.PENDING,
        )
    ).scalar()
    if existing:
        raise HTTPException(status_code=400, detail="Pending approval already exists for this conversation")

    approval = Approval(
        conversation_id=body.conversation_id,
        submitted_by=user.id,
        reason=body.reason,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return {
        "id": approval.id,
        "status": approval.status.value,
        "conversation_id": approval.conversation_id,
    }


@router.get("/pending")
def list_pending(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = (
        select(Approval)
        .where(Approval.status == ApprovalStatus.PENDING)
        .options(joinedload(Approval.conversation))
        .order_by(Approval.created_at.desc())
    )
    rows = db.execute(q).unique().scalars().all()
    return {
        "object": "list",
        "data": [
            {
                "id": a.id,
                "conversation_id": a.conversation_id,
                "customer_name": a.conversation.customer_name if a.conversation else None,
                "submitted_by": a.submitted_by,
                "reason": a.reason,
                "created_at": a.created_at.isoformat(),
            }
            for a in rows
        ],
    }


@router.post("/{approval_id}/action")
def handle_approval(
    approval_id: int,
    body: ActionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER)),
):
    approval = db.get(Approval, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(status_code=400, detail="Already processed")

    approval.status = ApprovalStatus.APPROVED if body.action == "approve" else ApprovalStatus.REJECTED
    approval.reviewed_by = user.id
    approval.updated_at = datetime.now(timezone.utc)

    # Add system message to conversation
    from models import Message
    db.add(Message(
        conversation_id=approval.conversation_id,
        sender="system",
        content=f"Approval {body.action}d by {user.username}" +
                (f": {body.comment}" if body.comment else ""),
    ))

    db.commit()
    return {"status": approval.status.value}
