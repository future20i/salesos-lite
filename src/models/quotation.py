"""Quotation — structured pricing data extracted from customer messages."""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, Float, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from src.models.base import Base


class Quotation(Base):
    """A structured quotation extracted from a lead's messages via LLM."""

    __tablename__ = "quotations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=False, index=True
    )
    source_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id"), nullable=True,
        comment="The message this quotation was extracted from",
    )

    # ── Quotation fields ──────────────────────────────────────────────
    product_name: Mapped[str] = mapped_column(String(512), nullable=False)
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True,
        comment="Unit of measure: pcs, kg, ton, set, etc.")
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD", nullable=False)

    # ── Terms ─────────────────────────────────────────────────────────
    validity_days: Mapped[int | None] = mapped_column(Integer, nullable=True,
        comment="How many days the quotation is valid for")
    incoterm: Mapped[str | None] = mapped_column(String(32), nullable=True,
        comment="e.g. FOB, CIF, EXW")
    port: Mapped[str | None] = mapped_column(String(128), nullable=True,
        comment="Destination port or delivery location")
    payment_terms: Mapped[str | None] = mapped_column(String(128), nullable=True,
        comment="e.g. T/T 30%, L/C at sight")

    # ── Metadata ──────────────────────────────────────────────────────
    notes: Mapped[str | None] = mapped_column(Text, nullable=True,
        comment="Additional context or remarks from extraction")
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False,
        comment="LLM extraction confidence score (0.0–1.0)")
    raw_extraction: Mapped[str | None] = mapped_column(Text, nullable=True,
        comment="Raw LLM JSON output for audit")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # ── Relationships ─────────────────────────────────────────────────
    lead: Mapped["Lead"] = relationship(back_populates="quotations")
