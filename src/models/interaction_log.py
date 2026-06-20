import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, JSON
from src.models.base import Base


class InteractionLog(Base):
    __tablename__ = "interaction_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    person_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person_profiles.id"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True
    )

    interaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # message | call | visit | event | other

    channel: Mapped[str | None] = mapped_column(String(32), nullable=True)

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    personal_topics: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ["family","hobby","career",...]

    key_takeaways: Mapped[str | None] = mapped_column(Text, nullable=True)

    tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ["milestone","follow-up-needed",...]

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
