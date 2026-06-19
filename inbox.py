from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session, joinedload

from models import Conversation, Message, ConvSource, ConvStatus, User, UserRole
from database import get_db
from auth import get_current_user, require_role

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


# ── Schemas ────────────────────────────────────────────────────────

class CreateConvRequest(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=128)
    source: ConvSource = ConvSource.WEB
    source_ref: str | None = None
    assigned_to: int | None = None
    initial_message: str | None = None


class ReplyRequest(BaseModel):
    content: str = Field(..., min_length=1)


class AssignRequest(BaseModel):
    user_id: int


class ConvSummary(BaseModel):
    id: int
    customer_name: str
    source: str
    assigned_to: int | None
    assignee_name: str | None
    status: str
    last_message: str | None
    last_message_at: str | None
    message_count: int

    class Config:
        from_attributes = True


class ConvDetail(ConvSummary):
    messages: list[dict]


# ── Helpers ────────────────────────────────────────────────────────

def _summarise(conv: Conversation) -> dict:
    last_msg = conv.messages[-1] if conv.messages else None
    return {
        "id": conv.id,
        "customer_name": conv.customer_name,
        "source": conv.source.value if conv.source else "web",
        "assigned_to": conv.assigned_to,
        "assignee_name": conv.assignee.username if conv.assignee else None,
        "status": conv.status.value if conv.status else "open",
        "last_message": last_msg.content[:120] if last_msg else None,
        "last_message_at": last_msg.created_at.isoformat() if last_msg else None,
        "message_count": len(conv.messages),
    }


# ── Routes ─────────────────────────────────────────────────────────

@router.get("/conversations")
def list_conversations(
    status: str | None = Query(None, pattern="^(open|closed)$"),
    source: str | None = Query(None),
    mine: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List conversations. Filter by status, source, or 'mine' (assigned to me)."""
    q = select(Conversation).options(joinedload(Conversation.messages), joinedload(Conversation.assignee))
    conditions = []

    if status:
        conditions.append(Conversation.status == ConvStatus(status))
    if source:
        conditions.append(Conversation.source == ConvSource(source))

    if mine:
        conditions.append(Conversation.assigned_to == user.id)
    elif user.role == UserRole.REP:
        # Reps see only their own unless admin/mgr
        conditions.append(Conversation.assigned_to == user.id)

    if conditions:
        q = q.where(and_(*conditions))

    q = q.order_by(Conversation.created_at.desc()).limit(200)
    rows = db.execute(q).unique().scalars().all()

    return {"object": "list", "data": [_summarise(c) for c in rows]}


@router.get("/conversations/{conv_id}")
def get_conversation(
    conv_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = db.get(Conversation, conv_id, options=[joinedload(Conversation.messages), joinedload(Conversation.assignee)])
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if user.role == UserRole.REP and conv.assigned_to != user.id:
        raise HTTPException(status_code=403, detail="Not your conversation")

    data = _summarise(conv)
    data["messages"] = [
        {"id": m.id, "sender": m.sender, "content": m.content, "created_at": m.created_at.isoformat()}
        for m in conv.messages
    ]
    return {"object": "conversation", "data": data}


@router.post("/conversations")
def create_conversation(
    body: CreateConvRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = Conversation(
        customer_name=body.customer_name,
        source=body.source,
        source_ref=body.source_ref,
        assigned_to=body.assigned_to,
    )
    db.add(conv)
    db.flush()

    if body.initial_message:
        db.add(Message(conversation_id=conv.id, sender="customer", content=body.initial_message))
    else:
        db.add(Message(conversation_id=conv.id, sender="system",
                       content=f"Conversation created by {user.username}"))

    db.commit()
    db.refresh(conv)
    return {"object": "conversation", "data": _summarise(conv)}


@router.post("/conversations/{conv_id}/reply")
def reply(
    conv_id: int,
    body: ReplyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if conv.status == ConvStatus.CLOSED:
        raise HTTPException(status_code=400, detail="Conversation is closed")

    msg = Message(conversation_id=conv_id, sender=user.username, content=body.content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {"id": msg.id, "sender": msg.sender, "content": msg.content, "created_at": msg.created_at.isoformat()}


@router.post("/conversations/{conv_id}/assign")
def assign(
    conv_id: int,
    body: AssignRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.ADMIN, UserRole.MANAGER)),
):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    target = db.get(User, body.user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    old = conv.assigned_to
    conv.assigned_to = body.user_id
    db.add(Message(conversation_id=conv_id, sender="system",
                   content=f"Reassigned from user#{old} to {target.username} by {user.username}"))
    db.commit()
    return {"assigned_to": body.user_id, "assignee_name": target.username}


@router.post("/conversations/{conv_id}/close")
def close_conv(
    conv_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conv = db.get(Conversation, conv_id)
    if not conv:
        raise HTTPException(status_code=404)
    conv.status = ConvStatus.CLOSED
    db.add(Message(conversation_id=conv_id, sender="system",
                   content=f"Closed by {user.username}"))
    db.commit()
    return {"status": "closed"}


@router.get("/stats")
def inbox_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    total = db.scalar(select(func.count(Conversation.id)).where(Conversation.status == ConvStatus.OPEN))
    assigned = db.scalar(select(func.count(Conversation.id)).where(
        and_(Conversation.status == ConvStatus.OPEN, Conversation.assigned_to == user.id)
    ))
    return {"open": total, "assigned_to_me": assigned}
