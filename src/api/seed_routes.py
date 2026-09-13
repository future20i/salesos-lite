"""Seed pipeline — demo opportunities with simulated conversations.

POST /api/seed/pipeline  — create demo data for the current tenant
DELETE /api/seed/pipeline  — remove all demo data (opportunities + leads + messages + followups)
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.auth import get_current_user
from src.models.user import User
from src.models.tenant import Tenant
from src.models.lead import Lead, LeadStatus, Channel
from src.models.message import Message, MessageDirection
from src.models.opportunity import Opportunity, OpportunityStage
from src.models.followup import FollowupItem, FollowupStatus, ReviewLevel

router = APIRouter(prefix="/api/seed", tags=["seed"])

# ── Demo scenario definitions ───────────────────────────────────────────────

DEMO_SCENARIOS = [
    {
        "opp_name": "德国EcoPack GmbH 包装设备采购",
        "stage": OpportunityStage.NEEDS_CONFIRMATION,
        "value": 280000,
        "probability": 40,
        "days_ago": 7,
        "customer_name": "Markus Bauer (EcoPack)",
        "competitor": "意大利 COMAC 提供低价方案",
        "messages": [
            ("Markus Bauer", "Hi, we saw your automatic packaging line at Hannover Messe. Do you have a catalog and price list?", MessageDirection.INBOUND, "web", -7),
            ("Zhang Wei (Sales)", "您好 Markus！感谢关注。这是我们最新的包装线目录和参考报价，请查看附件。贵司主要包装什么类型的产品？", MessageDirection.OUTBOUND, "web", -6),
            ("Markus Bauer", "Mainly food-grade PET containers, 500ml-2L. Our current throughput is 6000 bph, we need to scale to 12000. What's your max speed?", MessageDirection.INBOUND, "web", -5),
            ("Zhang Wei (Sales)", "我们的旗舰型号 TL-8000 最高可达 15000 bph，支持食品级认证。可否发一些你们现有产线的照片？我们做个初步方案。", MessageDirection.OUTBOUND, "web", -4),
            ("Markus Bauer", "Photos sent via email. Also, we need CE certification and a 2-year warranty. What's your typical delivery time?", MessageDirection.INBOUND, "web", -3),
        ],
        "followups": [
            {"title": "发送 CE 认证文件", "status": FollowupStatus.TODO, "priority": 1, "review": ReviewLevel.ROUTINE},
            {"title": "确认产能需求细节（12000 bph 场景）", "status": FollowupStatus.IN_PROGRESS, "priority": 2, "review": ReviewLevel.CRITICAL},
            {"title": "准备初步方案书 + 报价范围", "status": FollowupStatus.PENDING_REVIEW, "priority": 1, "review": ReviewLevel.COMMERCIAL,
             "draft": "Dear Markus,\n\nBased on your requirements for 12000 bph PET container packaging, we recommend our TL-8000 model:\n\n- Speed: 8000-15000 bph (adjustable)\n- CE certified (EN 415-10 compliant)\n- 2-year standard warranty, extendable to 5 years\n- Delivery: 12-14 weeks after PO confirmation\n- Estimated price range: EUR 240,000-280,000 FOB Shanghai\n\nWould you like us to arrange a video call next week to go through the technical details?\n\nBest regards,\nZhang Wei"},
        ],
    },
    {
        "opp_name": "泰国ThaiBev 灌装线改造项目",
        "stage": OpportunityStage.TECHNICAL_EXCHANGE,
        "value": 450000,
        "probability": 60,
        "days_ago": 14,
        "customer_name": "Somchai Rattanakosin (ThaiBev Engineering)",
        "competitor": "德国 Krones 技术方案更全面但价格高 60%",
        "messages": [
            ("Somchai Rattanakosin", "Sawadee krub. We're upgrading our canning line in Bangkok factory. Need a complete solution from depalletizer to palletizer. Capacity 30000 cph.", MessageDirection.INBOUND, "email", -14),
            ("Zhang Wei (Sales)", "Dear Somchai, thank you for reaching out. For 30000 cph canning, we have a proven integrated solution deployed in 4 factories across SEA. I'll share our reference cases.", MessageDirection.OUTBOUND, "email", -13),
            ("Somchai Rattanakosin", "Thank you. We received Krones' proposal — EUR 720k complete line. Can you provide a comparable quotation? Also, we need local installation support in Thailand.", MessageDirection.INBOUND, "email", -10),
            ("Zhang Wei (Sales)", "We can definitely beat Krones on price. Our Thailand partner SiamTech provides local installation and 24/7 support. I'm preparing the technical comparison sheet.", MessageDirection.OUTBOUND, "email", -9),
            ("Somchai Rattanakosin", "Good. Please also include: (1) energy consumption data, (2) changeover time between can sizes, (3) spare parts availability in Bangkok. Our board meeting is in 3 weeks.", MessageDirection.INBOUND, "email", -8),
            ("Zhang Wei (Sales)", "收到。我会在 3 天内给出完整技术方案，包括能耗数据、换型时间和备件方案。另外我们在曼谷有备件仓。", MessageDirection.OUTBOUND, "email", -7),
        ],
        "followups": [
            {"title": "完成技术对比表 (Krones vs 我方)", "status": FollowupStatus.IN_PROGRESS, "priority": 3, "review": ReviewLevel.CRITICAL},
            {"title": "准备能耗数据 + 换型时间文档", "status": FollowupStatus.TODO, "priority": 2, "review": ReviewLevel.ROUTINE},
            {"title": "确认曼谷备件仓库存清单", "status": FollowupStatus.TODO, "priority": 1, "review": ReviewLevel.ROUTINE},
            {"title": "起草完整技术方案书", "status": FollowupStatus.TODO, "priority": 2, "review": ReviewLevel.COMMERCIAL,
             "draft": "Dear Somchai,\n\nPlease find attached our technical comparison against Krones' proposal:\n\n| Item | Krones | Our Solution |\n|------|--------|-------------|\n| Price | EUR 720k | EUR 420-450k |\n| Speed | 30000 cph | 30000 cph |\n| Energy | 185 kWh | 152 kWh (18% lower) |\n| Changeover | 45 min | 30 min |\n| Local support | Via distributor | Direct partner SiamTech |\n| Spare parts | 2-week lead | Bangkok warehouse, 24h delivery |\n\nWe're confident in delivering a superior solution at a significantly better value. Looking forward to your board meeting — we can prepare an executive summary if helpful.\n\nBest regards,\nZhang Wei"},
        ],
    },
    {
        "opp_name": "巴西BevTech 年度集采框架",
        "stage": OpportunityStage.QUOTATION_NEGOTIATION,
        "value": 1200000,
        "probability": 75,
        "days_ago": 21,
        "customer_name": "Carlos Oliveira (BevTech Procurement)",
        "competitor": "本地供应商 Famabras 报价更低但不满足食品安全认证",
        "messages": [
            ("Carlos Oliveira", "Olá! We're looking for a 3-year framework agreement for packaging machinery. Estimated annual volume: 3-4 complete lines. Can you quote this?", MessageDirection.INBOUND, "whatsapp", -21),
            ("Zhang Wei (Sales)", "Olá Carlos! Absolutely. 3-year framework with 3-4 lines per year — that's exactly our sweet spot. What's your target price range per line?", MessageDirection.OUTBOUND, "whatsapp", -20),
            ("Carlos Oliveira", "Our budget is $200k-350k per line depending on capacity. But we need ANVISA compliance (Brazil FDA) and 5-year spare parts guarantee.", MessageDirection.INBOUND, "whatsapp", -18),
            ("Zhang Wei (Sales)", "We have ANVISA certification for all our food-grade equipment. 5-year spares guarantee is standard for framework agreements. Let me prepare a detailed proposal.", MessageDirection.OUTBOUND, "whatsapp", -16),
            ("Carlos Oliveira", "Famabras quoted $180k/line but their certification is incomplete. Our legal team prefers certified suppliers. When can you send the formal proposal?", MessageDirection.INBOUND, "whatsapp", -14),
            ("Zhang Wei (Sales)", "We can submit the formal proposal by this Friday. Our pricing will be competitive despite being fully certified — I think you'll be pleasantly surprised.", MessageDirection.OUTBOUND, "whatsapp", -12),
            ("Carlos Oliveira", "Great. Also, can you include a site visit plan? Our VP wants to visit your factory before signing the framework.", MessageDirection.INBOUND, "whatsapp", -10),
            ("Zhang Wei (Sales)", "当然可以！我们可以安排 2-3 天的工厂参观，包括生产车间、测试中心和已交付的类似项目。我会把行程草案放在方案书里。", MessageDirection.OUTBOUND, "whatsapp", -9),
            ("Carlos Oliveira", "Perfeito. One more thing — payment terms. Can you accept 30% advance, 60% upon shipment, 10% after commissioning?", MessageDirection.INBOUND, "whatsapp", -7),
        ],
        "followups": [
            {"title": "提交正式框架协议方案书", "status": FollowupStatus.IN_PROGRESS, "priority": 3, "review": ReviewLevel.CRITICAL,
             "draft": "Dear Carlos,\n\nPlease find attached our 3-year framework agreement proposal:\n\n- Annual volume: 3-4 complete packaging lines\n- Price per line: $220k-$340k (depending on capacity & configuration)\n- ANVISA certified (cert #BR-2024-0882)\n- 5-year spare parts guarantee included\n- Payment: 30% advance / 60% shipment / 10% commissioning ✅ Accepted\n- Site visit: 3-day factory tour, customizable dates\n\nOur proposal beats Famabras on certification, warranty, and total lifecycle cost despite a moderately higher unit price.\n\nLooking forward to hosting your VP at our factory!\n\nBest regards,\nZhang Wei"},
            {"title": "确认付款条件 (30/60/10)", "status": FollowupStatus.PENDING_REVIEW, "priority": 2, "review": ReviewLevel.COMMERCIAL},
            {"title": "准备工厂参观行程草案", "status": FollowupStatus.TODO, "priority": 1, "review": ReviewLevel.ROUTINE},
        ],
    },
]


# ── Helpers ─────────────────────────────────────────────────────────────────

def _is_seeded(name: str) -> bool:
    """Check if an opportunity name looks like demo seed data."""
    return any(s["opp_name"] in (name or "") for s in DEMO_SCENARIOS)


# ── Routes ──────────────────────────────────────────────────────────────────

@router.post("/pipeline", status_code=status.HTTP_201_CREATED)
async def seed_pipeline(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create demo opportunities with simulated conversations and follow-ups.

    Idempotent: if demo data already exists for this tenant, returns a
    message indicating it was already seeded.
    """
    tenant_id = current_user.tenant_id
    now = datetime.now(timezone.utc)

    # Check if already seeded
    result = await db.execute(
        select(Opportunity).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.name.in_([s["opp_name"] for s in DEMO_SCENARIOS]),
        )
    )
    if result.scalars().first():
        return {"status": "already_seeded", "message": "演示数据已存在。如需重新生成，请先清除。"}

    created = {"opportunities": 0, "leads": 0, "messages": 0, "followups": 0}

    for scenario in DEMO_SCENARIOS:
        # Create lead
        lead = Lead(
            tenant_id=tenant_id,
            customer_name=scenario["customer_name"],
            channel=Channel.WEB,
            status=LeadStatus.FOLLOWING,
            last_activity_at=now - timedelta(days=scenario.get("last_msg_days", 3)),
        )
        db.add(lead)
        await db.flush()
        created["leads"] += 1

        # Create opportunity
        opp = Opportunity(
            tenant_id=tenant_id,
            lead_id=lead.id,
            name=scenario["opp_name"],
            stage=scenario["stage"],
            value=scenario["value"],
            probability=scenario["probability"],
            expected_close_date=now + timedelta(days=90),
            competitor_tracking={"competitors": [scenario["competitor"]]},
            notes=f"演示商机 — {scenario['stage'].value}阶段",
            created_at=now - timedelta(days=scenario["days_ago"]),
        )
        db.add(opp)
        await db.flush()
        created["opportunities"] += 1

        # Create messages
        for sender, content, direction, channel, days_offset in scenario["messages"]:
            msg = Message(
                tenant_id=tenant_id,
                lead_id=lead.id,
                sender=sender,
                content=content,
                direction=direction,
                channel=channel,
                created_at=now + timedelta(days=days_offset),
            )
            db.add(msg)
            created["messages"] += 1

        # Create followup items
        for i, fu in enumerate(scenario["followups"]):
            item = FollowupItem(
                opportunity_id=opp.id,
                tenant_id=tenant_id,
                title=fu["title"],
                status=fu["status"],
                priority=fu.get("priority", 0),
                review_level=fu.get("review", ReviewLevel.COMMERCIAL),
                ai_draft=fu.get("draft"),
                created_at=now - timedelta(days=scenario["days_ago"] - i),
            )
            db.add(item)
            created["followups"] += 1

    await db.commit()

    return {
        "status": "seeded",
        "message": f"已创建 {created['opportunities']} 个演示商机、{created['leads']} 个客户、{created['messages']} 条对话、{created['followups']} 个跟进项",
        **created,
    }


@router.delete("/pipeline", status_code=status.HTTP_200_OK)
async def clear_seed_pipeline(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove all demo seed data for the current tenant.

    Deletes: followup_items, messages, opportunities, and leads that were
    created by seed_pipeline.
    """
    tenant_id = current_user.tenant_id

    # Find seeded opportunities
    opp_result = await db.execute(
        select(Opportunity).where(
            Opportunity.tenant_id == tenant_id,
            Opportunity.name.in_([s["opp_name"] for s in DEMO_SCENARIOS]),
        )
    )
    opps = opp_result.scalars().all()

    if not opps:
        return {"status": "not_found", "message": "没有找到演示数据"}

    opp_ids = [o.id for o in opps]
    lead_ids = [o.lead_id for o in opps if o.lead_id]

    # Delete followup items for these opportunities
    fu_result = await db.execute(
        delete(FollowupItem).where(FollowupItem.opportunity_id.in_(opp_ids))
    )
    fu_deleted = fu_result.rowcount

    # Delete opportunities
    opp_deleted_result = await db.execute(
        delete(Opportunity).where(Opportunity.id.in_(opp_ids))
    )
    opp_deleted = opp_deleted_result.rowcount

    # Delete messages for these leads
    msg_deleted = 0
    if lead_ids:
        msg_result = await db.execute(
            delete(Message).where(Message.lead_id.in_(lead_ids))
        )
        msg_deleted = msg_result.rowcount

    # Delete leads
    lead_deleted = 0
    if lead_ids:
        ld_result = await db.execute(
            delete(Lead).where(Lead.id.in_(lead_ids))
        )
        lead_deleted = ld_result.rowcount

    await db.commit()

    return {
        "status": "cleared",
        "message": f"已清除 {opp_deleted} 个商机、{lead_deleted} 个客户、{msg_deleted} 条消息、{fu_deleted} 个跟进项",
        "opportunities_deleted": opp_deleted,
        "leads_deleted": lead_deleted,
        "messages_deleted": msg_deleted,
        "followups_deleted": fu_deleted,
    }
