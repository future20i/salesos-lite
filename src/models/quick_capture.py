"""QuickCapture — voice/text notes captured during visits/calls/exhibitions.

Each capture is parsed by AI to extract action items, customer references,
and key dates, then converted into followup items linked to opportunities.
"""

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSON
from src.models.base import Base


class CaptureStatus(str):
    RAW = "raw"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class QuickCapture(Base):
    __tablename__ = "quick_captures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # Raw input
    source_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="text"
    )  # text / voice
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional context hints from the user
    customer_hint: Mapped[str | None] = mapped_column(String(256), nullable=True)
    opportunity_hint: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Processing state
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="raw"
    )  # raw / processing / done / failed
    # AI parsing result
    parsed: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    #    parsed = {
    #        "summary": "一行摘要",
    #        "customer_match": "客户名" | null,
    #        "action_items": [{"title": "...", "priority": 1, "assignee_hint": "..."}],
    #        "dates_mentioned": ["2026-07-15"],
    #        "products_mentioned": ["TL-8000"],
    #        "sentiment": "positive" | "neutral" | "concerned",
    #    }
    # Followup items created from this capture
    followup_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    #    ["uuid1", "uuid2", ...]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
