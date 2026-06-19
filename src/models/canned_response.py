import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, Enum as SAEnum, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from src.models.base import Base
import enum


class ResponseCategory(str, enum.Enum):
    INQUIRY_REPLY = "inquiry_reply"
    QUOTATION_FOLLOWUP = "quotation_followup"
    SAMPLE_FOLLOWUP = "sample_followup"
    HOLIDAY_GREETING = "holiday_greeting"
    ORDER_NUDGE = "order_nudge"
    REVIVAL = "revival"


class CannedResponse(Base):
    __tablename__ = "canned_responses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    category: Mapped[ResponseCategory] = mapped_column(
        SAEnum(ResponseCategory), nullable=False
    )
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
