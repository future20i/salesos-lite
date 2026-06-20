"""FollowupItem + FollowupEvent — actionable tasks within opportunities."""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSON
from src.models.base import Base
import enum


class FollowupStatus(str, enum.Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    PENDING_REVIEW = "pending_review"
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
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=False, index=True
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
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    followup: Mapped["FollowupItem"] = relationship(back_populates="events")
