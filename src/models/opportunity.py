"""Opportunity model — B2B sales pipeline stage tracking."""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Float, Text, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSON
from src.models.base import Base
import enum


class OpportunityStage(str, enum.Enum):
    LEAD_VALIDATION = "lead_validation"
    NEEDS_CONFIRMATION = "needs_confirmation"
    TECHNICAL_EXCHANGE = "technical_exchange"
    QUOTATION_NEGOTIATION = "quotation_negotiation"
    CONTRACT = "contract"
    WON = "won"
    LOST = "lost"
    SHELVED = "shelved"


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    probability: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage: Mapped[OpportunityStage] = mapped_column(
        SAEnum(OpportunityStage), nullable=False, default=OpportunityStage.LEAD_VALIDATION
    )
    expected_close_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    decision_chain: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    competitor_tracking: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="opportunities")
    lead: Mapped["Lead | None"] = relationship(back_populates="opportunity")
    followups: Mapped[list["FollowupItem"]] = relationship(
        back_populates="opportunity", order_by="FollowupItem.created_at"
    )
