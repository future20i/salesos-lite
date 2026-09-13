"""FollowupItem + FollowupEvent — actionable tasks within opportunities."""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSON
from src.models.base import Base
import enum


class FollowupStatus(str, enum.Enum):
    TRIAGE = "triage"          # AI-driven spec expansion column
    TODO = "todo"
    READY = "ready"            # Ready for agent dispatch
    IN_PROGRESS = "in_progress"
    PENDING_REVIEW = "pending_review"
    BLOCKED = "blocked"
    DONE = "done"


class ReviewLevel(str, enum.Enum):
    ROUTINE = "routine"
    COMMERCIAL = "commercial"
    CRITICAL = "critical"


class FollowupItem(Base):
    __tablename__ = "followup_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=True, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[FollowupStatus] = mapped_column(
        SAEnum(FollowupStatus), nullable=False, default=FollowupStatus.TODO
    )
    priority: Mapped[int] = mapped_column(Integer, default=0)
    assignee_agent: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # Hermes agent profile name that handles this task
    triage: Mapped[bool] = mapped_column(default=False)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    max_retries: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_level: Mapped[ReviewLevel] = mapped_column(
        SAEnum(ReviewLevel), nullable=False, default=ReviewLevel.COMMERCIAL
    )
    ai_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    opportunity: Mapped["Opportunity"] = relationship(back_populates="followups")
    events: Mapped[list["FollowupEvent"]] = relationship(
        back_populates="followup", order_by="FollowupEvent.created_at"
    )


class FollowupEvent(Base):
    __tablename__ = "followup_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    followup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("followup_items.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # created|specified|dispatched|claimed|heartbeat|completed|blocked|unblocked|reclaimed|archived|sent
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    run_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )  # FK to followup_runs when event is run-scoped
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    followup: Mapped["FollowupItem"] = relationship(back_populates="events")


class FollowupRun(Base):
    """Each agent execution attempt on a followup task."""

    __tablename__ = "followup_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    followup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("followup_items.id"), nullable=False, index=True
    )
    agent_profile: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # running|completed|failed|cancelled|reclaimed
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FollowupComment(Base):
    """Human/agent collaboration comments on followup tasks."""

    __tablename__ = "followup_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    followup_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("followup_items.id"), nullable=False, index=True
    )
    author: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # user.name or agent profile
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
