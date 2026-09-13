"""
DecisionStageRecord + CommunicationObservation + SignalExtraction
— 决策阶段诊断系统的数据模型（v3.1 收敛版）

设计原则：
- DecisionStageRecord: 追加式，不可覆盖，按 person 关联
- CommunicationObservation: AI 生成 + 人工确认，信号衰减
- SignalExtraction: 置信度分层，高→推送 / 中→待确认 / 低→训练
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    String, Integer, Text, DateTime, ForeignKey, Boolean, Float, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSON
from src.models.base import Base


# ═══════════════════════════════════════════════════════════
# DecisionStageRecord — 追加式阶段判定（按 person，不可覆盖）
# ═══════════════════════════════════════════════════════════

class DecisionStageRecord(Base):
    __tablename__ = "decision_stage_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    person_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person_profiles.id"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True,
    )

    # ── 核心判定 ──
    stage_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        # stage_a_problem_unawareness / stage_b_fear_of_failure
        # / stage_c_status_quo_bias / unclear
    )

    blockage_source: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        # personal_fear / upstream_approval / cross_dept_coordination / None
    )

    confidence: Mapped[str] = mapped_column(
        String(16), nullable=False, default="medium",
        # high / medium / low
    )

    signal_strength: Mapped[str] = mapped_column(
        String(16), nullable=False, default="normal",
        # sparse / normal / rich
    )

    # ── 可解释性 ──
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasoning_chain: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # [{matched_signal, theory_basis, rule_version}, ...]

    triggered_by_interaction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interaction_logs.id"), nullable=True,
    )

    # ── 冷却期追踪 ──
    override_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    override_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    # override_triggered=True & override_confirmed=False → 待二次确认

    # ── 版本追踪 ──
    engine_version: Mapped[str] = mapped_column(
        String(16), nullable=False, default="v3.1",
    )

    # ── 审计 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )


# ═══════════════════════════════════════════════════════════
# CommunicationObservation — 追加式情境观察（AI 生成 + 人工确认）
# ═══════════════════════════════════════════════════════════

class CommunicationObservation(Base):
    __tablename__ = "communication_observations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    person_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person_profiles.id"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True,
    )

    # ── 来源 ──
    interaction_log_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interaction_logs.id"), nullable=True,
    )
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 触发此观察的客户原话（用于后续审计）

    # ── 内容 ──
    observation: Mapped[str] = mapped_column(Text, nullable=False)

    signal_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # necessity_doubt / accountability_fear / status_quo_defense
    # / peer_validation_request / interaction_cessation / other

    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # AI 提取时的置信度 0.0-1.0

    human_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )

    # ── 衰减 ──
    signal_decay_days: Mapped[int] = mapped_column(Integer, default=30)
    # 超过此天数后置信度自动降权
    effective_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 当前有效置信度 = ai_confidence * decay_factor * confirmed_bonus

    # ── 审计 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


# ═══════════════════════════════════════════════════════════
# SignalExtraction — AI 信号提取结果（置信度分层推送）
# ═══════════════════════════════════════════════════════════

class SignalExtraction(Base):
    __tablename__ = "signal_extractions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    interaction_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("interaction_logs.id"),
        nullable=False, index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False, index=True,
    )

    # ── 原始输入 ──
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)

    # ── 提取结果 ──
    extracted_signals: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # [
    #   {signal_type, matched_phrase, confidence, rationale},
    #   ...
    # ]

    # ── 人工审查 ──
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending_confirmation",
    )
    # pending_confirmation / confirmed / rejected

    confirmed_signals: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 人工确认后筛选出的信号
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True,
    )

    # ── 模型信息 ──
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extraction_version: Mapped[str] = mapped_column(
        String(16), nullable=False, default="v3.1",
    )

    # ── 审计 ──
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
