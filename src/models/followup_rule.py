import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, Enum as SAEnum, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from src.models.base import Base
import enum


class TriggerType(str, enum.Enum):
    TIME_SINCE_CONTACT = "time_since_contact"
    TIME_SINCE_STATUS = "time_since_status"
    LEAD_INTENT = "lead_intent"


class ActionType(str, enum.Enum):
    SEND_TEMPLATE = "send_template"
    SEND_AI_REPLY = "send_ai_reply"
    ASSIGN_TO = "assign_to"


class FollowupRule(Base):
    __tablename__ = "followup_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    trigger_type: Mapped[TriggerType] = mapped_column(
        SAEnum(TriggerType), nullable=False
    )
    trigger_value: Mapped[str] = mapped_column(String(64), nullable=False)
    action_type: Mapped[ActionType] = mapped_column(
        SAEnum(ActionType), nullable=False
    )
    action_value: Mapped[str] = mapped_column(String(256), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class FollowupLog(Base):
    __tablename__ = "followup_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("followup_rules.id"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False, index=True
    )
    action_type: Mapped[ActionType] = mapped_column(
        SAEnum(ActionType), nullable=False
    )
    action_value: Mapped[str] = mapped_column(String(256), nullable=False)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
