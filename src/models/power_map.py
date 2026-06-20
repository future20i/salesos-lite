import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSON
from src.models.base import Base


class PowerMap(Base):
    __tablename__ = "power_maps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("opportunities.id"),
        nullable=False,
        index=True,
        unique=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )

    # 决策链上的每个人
    stakeholders: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # [{person_profile_id, role: "decision_maker"|"influencer"|"gatekeeper"|"user"|"coach",
    #   stance: "champion"|"neutral"|"opponent"|"unknown",
    #   concerns, influence_level: 1-10, notes}]

    # 关系网络
    connections: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # [{from_id, to_id, relationship_type, strength: 1-5}]

    # Strategy
    strategy_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
