import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.models.base import Base
import enum


class LeadStatus(str, enum.Enum):
    NEW = "new"
    FOLLOWING = "following"
    QUOTED = "quoted"
    SAMPLED = "sampled"
    NEGOTIATING = "negotiating"
    CLOSED = "closed"


class Intent(str, enum.Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    DORMANT = "dormant"


class Channel(str, enum.Enum):
    WEB = "web"
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[Channel] = mapped_column(
        SAEnum(Channel), nullable=False, default=Channel.WEB
    )
    status: Mapped[LeadStatus] = mapped_column(
        SAEnum(LeadStatus), nullable=False, default=LeadStatus.NEW
    )
    intent: Mapped[Intent | None] = mapped_column(SAEnum(Intent), nullable=True)
    # Customer profile (AI-extracted)
    target_price: Mapped[str | None] = mapped_column(String(128), nullable=True)
    inquired_sku: Mapped[str | None] = mapped_column(String(256), nullable=True)
    port: Mapped[str | None] = mapped_column(String(128), nullable=True)
    contact_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    competitor: Mapped[str | None] = mapped_column(String(256), nullable=True)
    lead_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unread: Mapped[bool] = mapped_column(Boolean, default=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=True, index=True
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="leads")
    assignee: Mapped["User | None"] = relationship(
        back_populates="assigned_leads", foreign_keys=[assigned_to]
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="lead", order_by="Message.created_at"
    )
    quotations: Mapped[list["Quotation"]] = relationship(
        back_populates="lead", order_by="Quotation.created_at"
    )
    opportunity: Mapped["Opportunity | None"] = relationship(
        back_populates="lead", foreign_keys=[opportunity_id]
    )
