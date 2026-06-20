# PersonProfile — 人脉画像，4层理解深度
# Layer 1: 商业需求 (team-shared) — already in Lead/Opportunity
# Layer 2: 个人画像 (creator + superior) — 麦凯66核心
# Layer 3: 决策驱动力 (creator only, ENCRYPTED) 
# Layer 4: 影响力杠杆 (creator only, ENCRYPTED)

import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSON
from src.models.base import Base

class PersonProfile(Base):
    __tablename__ = "person_profiles"
    
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True, index=True)
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("opportunities.id"), nullable=True, index=True)
    
    # Layer 2: 个人画像 (麦凯66核心)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 职位
    birthday: Mapped[str | None] = mapped_column(String(32), nullable=True)  # ISO date string "MM-DD" or full
    hometown: Mapped[str | None] = mapped_column(String(256), nullable=True)
    education: Mapped[str | None] = mapped_column(String(512), nullable=True)
    personality_tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ["analytical","relationship-builder",...]
    spouse_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    spouse_occupation: Mapped[str | None] = mapped_column(String(256), nullable=True)
    children_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # [{name, age, school, milestone}]
    interests: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # [{category, detail, note}]
    
    # Layer 3: 决策驱动力 (加密字段)
    core_fear: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted
    core_ambition: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted
    org_situation: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted
    trust_foundation: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted
    
    # Layer 4: 影响力杠杆 (加密字段)
    leverage_points: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # encrypted [{type, detail, status}]
    relationship_activities: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # encrypted [{type, date, detail, outcome}]
    
    # 关系健康度
    relationship_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-10
    last_personal_touch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # 权限控制
    encrypted_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # ["core_fear","core_ambition",...]
    access_list: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # [{user_id, access_level: "full"|"layer2_only"}]
    
    # Audit
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
