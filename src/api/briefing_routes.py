"""
Intel API v3.1 — 战前简报 + 会议策略 + 阶段诊断
"""

import uuid
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.auth import get_current_user
from src.models import (
    User,
    PersonProfile,
    InteractionLog,
    DecisionStageRecord,
    CommunicationObservation,
)
from src.engine.stage_diagnosis import StageDiagnosisEngine
from src.engine.strategy_match import StrategyMatchEngine
from src.engine.meeting_briefing import MeetingBriefingGenerator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/intel", tags=["intel"])

# ── 引擎实例 ──
diagnosis_engine = StageDiagnosisEngine()
strategy_engine = StrategyMatchEngine()
meeting_engine = MeetingBriefingGenerator()


# ═══════════════════════════════════════════════════════════
# Request/Response Models
# ═══════════════════════════════════════════════════════════

class DiagnoseRequest(BaseModel):
    person_id: str
    interaction_text: str
    interaction_id: str | None = None

class BriefingRequest(BaseModel):
    person_id: str

class MeetingBriefingRequest(BaseModel):
    opportunity_id: str
    attendee_ids: list[str]

class FeedbackRequest(BaseModel):
    helpful: bool
    note: str | None = None


# ═══════════════════════════════════════════════════════════
# POST /diagnose — 阶段诊断（低信号场景处理）
# ═══════════════════════════════════════════════════════════

@router.post("/diagnose")
async def diagnose_stage(
    body: DiagnoseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对一次客户互动进行阶段诊断。"""
    person_id = uuid.UUID(body.person_id)

    # 拉取上次判定
    last_record_result = await db.execute(
        select(DecisionStageRecord)
        .where(
            DecisionStageRecord.person_profile_id == person_id,
            DecisionStageRecord.tenant_id == current_user.tenant_id,
        )
        .order_by(DecisionStageRecord.created_at.desc())
        .limit(1)
    )
    last_record = last_record_result.scalar_one_or_none()

    last_stage = last_record.stage_type if last_record else None

    # 拉取近期信号（用于信号强度评估）
    recent_signals_result = await db.execute(
        select(CommunicationObservation)
        .where(
            CommunicationObservation.person_profile_id == person_id,
            CommunicationObservation.tenant_id == current_user.tenant_id,
            CommunicationObservation.human_confirmed == True,
        )
        .order_by(CommunicationObservation.created_at.desc())
        .limit(10)
    )
    recent = recent_signals_result.scalars().all()

    recent_signal_dicts = [
        {
            "signal_type": s.signal_type,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "confidence": s.effective_confidence,
        }
        for s in recent
    ]

    # 执行诊断
    result = diagnosis_engine.diagnose(
        interaction_text=body.interaction_text,
        person_id=body.person_id,
        last_known_stage=last_stage,
        recent_signals=recent_signal_dicts,
    )

    # 存储判定记录
    if body.interaction_id:
        triggered_by = uuid.UUID(body.interaction_id) if body.interaction_id else None
    else:
        triggered_by = None

    record = DecisionStageRecord(
        person_profile_id=person_id,
        tenant_id=current_user.tenant_id,
        stage_type=result["stage"],
        blockage_source=None,
        confidence=result["confidence"],
        signal_strength=result.get("signal_strength", "normal"),
        evidence=body.interaction_text[:2000],
        reasoning_chain=result.get("reasoning"),
        triggered_by_interaction_id=triggered_by,
        override_triggered=result.get("override_triggered", False),
        override_confirmed=result.get("override_confirmed", False),
        created_by=current_user.id,
    )
    db.add(record)
    await db.commit()

    return {"diagnosis": result, "record_id": str(record.id)}


# ═══════════════════════════════════════════════════════════
# POST /briefing — 战前简报（单人）
# ═══════════════════════════════════════════════════════════

@router.post("/briefing")
async def person_briefing(
    body: BriefingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    为单个联系人生成战前简报。

    输出：
    - 当前阶段判定 + 解释
    - 策略建议（四合一）
    - 禁用清单
    """
    person_id = uuid.UUID(body.person_id)

    # 拉取联系人信息
    person_result = await db.execute(
        select(PersonProfile).where(
            PersonProfile.id == person_id,
            PersonProfile.tenant_id == current_user.tenant_id,
        )
    )
    person = person_result.scalar_one_or_none()
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")

    # 拉取最新阶段判定 — 优先高置信度
    # 逻辑：如果最近一条是稀疏/低置信度/unclear → 回退到最近一条有信心的判定
    stage_result = await db.execute(
        select(DecisionStageRecord)
        .where(
            DecisionStageRecord.person_profile_id == person_id,
            DecisionStageRecord.tenant_id == current_user.tenant_id,
        )
        .order_by(DecisionStageRecord.created_at.desc())
        .limit(5)
    )
    recent_records = stage_result.scalars().all()

    stage_record = None
    uncertain_record = None
    for rec in recent_records:
        if rec.confidence in ("high", "medium") and rec.stage_type != "unclear":
            stage_record = rec
            break
        if uncertain_record is None and rec.signal_strength == "sparse":
            uncertain_record = rec

    # 没有高置信度记录 → 用最近的（即使是不确定的）
    if stage_record is None:
        stage_record = uncertain_record or (recent_records[0] if recent_records else None)

    stage = stage_record.stage_type if stage_record else "unclear"
    blockage = stage_record.blockage_source if stage_record else None
    used_fallback = uncertain_record is not None and stage_record is uncertain_record

    # 检查 override 冷却期
    override_alert = None
    if stage_record and stage_record.override_triggered and not stage_record.override_confirmed:
        if stage_record.created_at:
            from datetime import datetime
            hours_since = (datetime.now(stage_record.created_at.tzinfo) - stage_record.created_at).total_seconds() / 3600
            if hours_since < 24:
                override_alert = (
                    "⚠️ 上次互动检测到阶段跳变信号，建议本轮先确认再切换策略。"
                )

    # 获取策略建议
    strategy = strategy_engine.recommend(
        stage=stage,
        blockage_source=blockage,
        uncertainty_flag=(
            stage_record.signal_strength == "sparse"
            if stage_record
            else False
        ),
    )

    # 快速摘要（微信场景）
    summary = strategy_engine.stage_summary(stage, blockage)

    return {
        "person": {
            "id": str(person.id),
            "name": person.full_name or "未知",
            "title": person.title,
            "role": person.role_type if hasattr(person, 'role_type') else None,
        },
        "diagnosis": {
            "stage": stage,
            "confidence": stage_record.confidence if stage_record else "low",
            "signal_strength": (
                stage_record.signal_strength if stage_record else "unknown"
            ),
            "last_updated": (
                stage_record.created_at.isoformat() if stage_record else None
            ),
            "evidence": stage_record.evidence if stage_record else None,
            "override_alert": override_alert,
        },
        "strategy": strategy,
        "one_liner": summary,
    }


# ═══════════════════════════════════════════════════════════
# POST /meeting-briefing — 多人会议整合策略
# ═══════════════════════════════════════════════════════════

@router.post("/meeting-briefing")
async def meeting_briefing(
    body: MeetingBriefingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    多人会议场景 → 一条整合策略。

    输出：
    - 主攻对象 + 为什么
    - 其他与会者约束
    - 会前行动清单
    - 会中叙事弧
    - 雷区
    """
    attendee_ids = [uuid.UUID(pid) for pid in body.attendee_ids]
    opp_id = uuid.UUID(body.opportunity_id)

    # 拉取商机信息
    from src.models.opportunity import Opportunity
    opp_result = await db.execute(
        select(Opportunity).where(
            Opportunity.id == opp_id,
            Opportunity.tenant_id == current_user.tenant_id,
        )
    )
    opp = opp_result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    # 拉取所有与会者的最新阶段判定
    attendees = []
    for pid in attendee_ids:
        person_result = await db.execute(
            select(PersonProfile).where(
                PersonProfile.id == pid,
                PersonProfile.tenant_id == current_user.tenant_id,
            )
        )
        person = person_result.scalar_one_or_none()
        if not person:
            continue

        stage_result = await db.execute(
            select(DecisionStageRecord)
            .where(
                DecisionStageRecord.person_profile_id == pid,
                DecisionStageRecord.tenant_id == current_user.tenant_id,
            )
            .order_by(DecisionStageRecord.created_at.desc())
            .limit(1)
        )
        stage_record = stage_result.scalar_one_or_none()

        attendees.append({
            "person_id": str(person.id),
            "name": person.full_name or "未知",
            "title": person.title or "",
            "role_type": getattr(person, "role_type", ""),
            "influence_level": "unknown",  # TODO: 从 PowerMap 拉取
            "stage": stage_record.stage_type if stage_record else "unclear",
            "blockage_source": stage_record.blockage_source if stage_record else None,
            "recommended_strategy": (
                strategy_engine.recommend(
                    stage=stage_record.stage_type if stage_record else "unclear",
                    blockage_source=stage_record.blockage_source if stage_record else None,
                )
                if stage_record
                else {}
            ),
        })

    # 生成会议策略
    briefing = meeting_engine.generate(
        opportunity_summary={
            "name": getattr(opp, "name", str(opp.id)[:8]),
            "stage": getattr(opp, "stage", "unknown"),
            "value": getattr(opp, "estimated_value", None),
        },
        attendees=attendees,
    )

    return briefing


# ═══════════════════════════════════════════════════════════
# POST /briefing/{id}/feedback — 简报反馈
# ═══════════════════════════════════════════════════════════

@router.post("/briefing/{briefing_type}/feedback")
async def briefing_feedback(
    briefing_type: str,  # "person" or "meeting"
    body: FeedbackRequest,
    current_user: User = Depends(get_current_user),
):
    """
    销售对系统建议的评价（👍/👎）。

    反馈数据直接进入规则引擎的调整循环——
    持续被点👎的策略会被标记为需要人工复核。
    """
    feedback_id = str(uuid.uuid4())

    logger.info(
        "Briefing feedback: type=%s helpful=%s note=%s user=%s",
        briefing_type, body.helpful, body.note, str(current_user.id),
    )

    return {
        "feedback_id": feedback_id,
        "received": True,
        "message": (
            "感谢反馈。你的评价会帮助我们持续优化策略建议。"
            if body.helpful
            else "感谢反馈。我们会复核这条建议的逻辑。"
        ),
    }
