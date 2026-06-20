"""Knowledge API — CRUD + seed endpoint for 3-tier knowledge base.

Tiers:
  1 — Global reference (seed data, non-editable/deletable)
  2 — Industry knowledge (brain_downlink source, non-editable/deletable by users)
  3 — Company-specific (user-managed, soft-delete)
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.user import User
from src.models.knowledge import KnowledgeEntry
from src.auth import get_current_user

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


# ── Schemas ───────────────────────────────────────────────────────

class KnowledgeCreate(BaseModel):
    tier: int = Field(default=3, ge=1, le=3, description="Knowledge tier (users may only create Tier 3)")
    category: str = Field(..., max_length=64)
    title: str = Field(..., max_length=256)
    content: str
    source: str = Field(default="manual", max_length=32)


class KnowledgeUpdate(BaseModel):
    category: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=256)
    content: str | None = None
    tier: int | None = Field(default=None, ge=1, le=3)
    is_active: bool | None = None


class KnowledgeResponse(BaseModel):
    id: str
    tenant_id: str
    tier: int
    category: str
    title: str
    content: str
    source: str
    is_active: bool
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_orm(cls, obj: KnowledgeEntry) -> "KnowledgeResponse":
        return cls(
            id=str(obj.id),
            tenant_id=str(obj.tenant_id),
            tier=obj.tier,
            category=obj.category,
            title=obj.title,
            content=obj.content,
            source=obj.source,
            is_active=obj.is_active,
            created_at=str(obj.created_at) if obj.created_at else None,
            updated_at=str(obj.updated_at) if obj.updated_at else None,
        )


# ── Seed data ─────────────────────────────────────────────────────

SEED_ENTRIES: list[dict] = [
    # ═══════ Tier 1: Global foreign trade reference (5 entries) ═══════
    {
        "tier": 1,
        "source": "manual",
        "category": "trade_terms",
        "title": "FOB vs CIF — 外贸术语详解",
        "content": (
            "FOB (Free On Board): 卖方在装运港将货物交到买方指定的船上即完成交货。"
            "风险在货物越过船舷时转移。买方负责海运、保险和目的港费用。\n\n"
            "CIF (Cost, Insurance and Freight): 卖方负责将货物运至目的港，并承担运费和保险费。"
            "风险仍在装运港货物越过船舷时转移给买方。\n\n"
            "选择建议：FOB适合买方有指定货代的场景，买方对物流有更多控制权；"
            "CIF适合买方希望简化流程、由卖方一站式负责运输的场景。"
        ),
    },
    {
        "tier": 1,
        "source": "manual",
        "category": "communication",
        "title": "跨时区沟通礼仪与最佳实践",
        "content": (
            "1. 了解客户所在时区，避免在对方非工作时间发送紧急消息。\n"
            "2. 邮件主题清晰标注[Action Required]/[FYI]/[Urgent]。\n"
            "3. 使用世界时钟工具（如 timeanddate.com）规划会议时间。\n"
            "4. 关键节点提前24小时确认，预留时差缓冲。\n"
            "5. 中东客户注意周五为休息日，以色列为周五日落至周六日落。\n"
            "6. 拉美客户午餐时间较长（12:00-14:00），避免此时段联系。"
        ),
    },
    {
        "tier": 1,
        "source": "manual",
        "category": "negotiation",
        "title": "外贸常见异议处理话术",
        "content": (
            "价格异议：'您的价格比竞争对手高20%' → 强调质量差异、认证资质、售后服务，"
            "提供分阶梯报价方案（不同起订量对应不同价格）。\n\n"
            "交期异议：'交期太长了' → 解释生产流程、品控环节，提供分批交货选项，"
            "急单可协调加急费缩短交期。\n\n"
            "付款条件异议：'我们只接受OA 60天' → 首单建议T/T 30%预付+70%见提单副本，"
            "长期合作客户可逐步放宽。中信保承保可降低风险。\n\n"
            "质量疑虑：'之前供应商出现过质量问题' → 提供样品、第三方检测报告、"
            "工厂审核邀请，承诺质量不达标全额退款。"
        ),
    },
    {
        "tier": 1,
        "source": "manual",
        "category": "quotation",
        "title": "标准报价单结构与编制要点",
        "content": (
            "报价单必备要素：\n"
            "1. 卖方信息（公司全称、地址、联系人、联系方式）\n"
            "2. 买方信息\n"
            "3. 报价单号与日期\n"
            "4. 产品明细：品名、规格型号、数量、单价、总价\n"
            "5. 贸易术语（FOB/CIF/EXW等）\n"
            "6. 付款条件（T/T, L/C, D/P等）\n"
            "7. 交期与包装方式\n"
            "8. 有效期（通常7-15天）\n"
            "9. 备注（认证要求、特殊条款等）\n\n"
            "要点：明确标注报价不含目的国关税/增值税；"
            "涉及汇率波动时添加汇率调整条款。"
        ),
    },
    {
        "tier": 1,
        "source": "manual",
        "category": "exhibition",
        "title": "展会跟进全流程指南",
        "content": (
            "展会前（展前2周）：\n"
            "- 筛选目标客户名单，发送展会邀请函\n"
            "- 准备产品样册、名片、样品\n"
            "- 预约重点客户见面时间\n\n"
            "展会中：\n"
            "- 记录每位到访客户的需求、关注点和后续行动\n"
            "- 拍照记录客户感兴趣的产品\n"
            "- 当天晚上发送简短感谢邮件\n\n"
            "展会后：\n"
            "- 24小时内发送详细跟进邮件+报价\n"
            "- 3天内确认客户是否收到并安排下一步\n"
            "- 1周后未回复则电话跟进\n"
            "- 将客户分级（A/B/C）录入CRM系统跟踪"
        ),
    },
    # ═══════ Tier 2: Industry knowledge (7 entries, brain_downlink source) ═══════
    {
        "tier": 2,
        "source": "brain_downlink",
        "category": "industry",
        "title": "飞轮UPS技术对比 — 主流方案概览",
        "content": (
            "飞轮UPS技术路线对比（数据中心场景）：\n\n"
            "1. Active Power CleanSource：磁悬浮轴承，转速7700 RPM，"
            "功率范围250-1000 kVA，效率98%。\n"
            "2. Vycon VDC：磁轴承+钢制飞轮，最高转速36000 RPM，"
            "适合高功率密度场景，功率250-2000 kVA。\n"
            "3. Piller PowerBridge：滚动轴承+真空腔体，"
            "动能存储时间15-30秒，主打工业级可靠性。\n"
            "4. Hitec Power Protection：柴油UPS+飞轮混合，"
            "适合长时间后备需求（分钟级）。\n\n"
            "选型要点：关注轴承类型（磁悬浮 vs 机械）、转速、"
            "备用时间、与柴油发电机切换的兼容性。"
        ),
    },
    {
        "tier": 2,
        "source": "brain_downlink",
        "category": "industry",
        "title": "飞轮UPS关键参数速查表",
        "content": (
            "关键参数及典型范围：\n"
            "- 功率范围：250 kVA - 2000 kVA（单模块）\n"
            "- 备用时间：10-30秒（飞轮仅提供过渡，需配合柴油发电机）\n"
            "- 效率：>97%（远高于电池UPS的92-95%）\n"
            "- 飞轮转速：7,700 - 36,000 RPM\n"
            "- 轴承类型：磁悬浮（免维护）/ 滚动轴承（需定期更换）\n"
            "- 工作温度：0°C - 40°C\n"
            "- 噪音：<75 dBA @ 1m\n"
            "- 占地面积：约为同等功率电池UPS的25-40%\n"
            "- 寿命：20年+（磁悬浮飞轮）/ 10-15年（机械轴承）\n"
            "- 切换时间：<2ms（在线双变换模式）\n"
            "- 充放电循环：无限次（无化学老化）"
        ),
    },
    {
        "tier": 2,
        "source": "brain_downlink",
        "category": "competitor",
        "title": "飞轮UPS竞品快速参考",
        "content": (
            "主要厂商及定位：\n\n"
            "Active Power（美国）：行业先驱，磁悬浮技术最成熟，"
            "全球装机量超5000台。优势：品牌认知度高、案例丰富。"
            "劣势：被Piller收购后产品线调整中。\n\n"
            "Vycon（美国）：高转速方案代表，36k RPM领先行业。"
            "优势：功率密度最高。劣势：价格较高，亚太服务网络有限。\n\n"
            "Piller（德国）：工业级飞轮UPS领导者。"
            "优势：德国制造品质、完整电力保护方案。劣势：价格最高。\n\n"
            "Hitec（荷兰）：柴油+飞轮混合方案独特。"
            "优势：适合长后备时间需求。劣势：系统复杂度高。\n\n"
            "国内厂商：中科正方、中达电通等正在追赶，目前以机械轴承方案为主。"
        ),
    },
    {
        "tier": 2,
        "source": "brain_downlink",
        "category": "industry",
        "title": "数据中心项目全生命周期概览",
        "content": (
            "阶段一：可行性研究（1-3个月）\n"
            "- 电力容量评估、选址分析、TCO估算\n"
            "- 确定Tier等级（III/IV）\n\n"
            "阶段二：设计阶段（2-4个月）\n"
            "- 概念设计→初步设计→施工图设计\n"
            "- 电力系统架构确定（2N/N+1/分布式）\n\n"
            "阶段三：设备采购（1-3个月）\n"
            "- UPS/柴油发电机/配电柜/冷却系统招标\n"
            "- 飞轮UPS vs 电池UPS评估节点\n\n"
            "阶段四：施工安装（3-6个月）\n"
            "- 土建→设备安装→布线→调试\n\n"
            "阶段五：验收与试运行（1-2个月）\n"
            "- 满载测试、故障模拟、72小时连续运行\n\n"
            "阶段六：运维（持续）\n"
            "- 飞轮UPS年检仅需轴承检查（磁悬浮免维护）"
        ),
    },
    {
        "tier": 2,
        "source": "brain_downlink",
        "category": "customer_profiles",
        "title": "客户画像 — 超大规模数据中心运营商",
        "content": (
            "典型客户：AWS、Azure、Google Cloud、Meta等超大规模云服务商\n\n"
            "决策特点：\n"
            "- 采购决策高度标准化，有严格的AVL（合格供应商名录）\n"
            "- 关注TCO（总拥有成本）而非初始采购价\n"
            "- 重视供应商的全球交付能力和本地服务支持\n"
            "- 通常要求通过现场审计和长时间测试验证\n"
            "- 合同周期长（3-5年框架协议）\n\n"
            "关键诉求：\n"
            "- 能效（PUE优化）\n"
            "- 可靠性（99.999%+）\n"
            "- 可扩展性（模块化部署）\n"
            "- 可持续发展（减少铅酸电池使用）"
        ),
    },
    {
        "tier": 2,
        "source": "brain_downlink",
        "category": "customer_profiles",
        "title": "客户画像 — 金融行业数据中心",
        "content": (
            "典型客户：银行、证券交易所、保险公司\n\n"
            "决策特点：\n"
            "- 合规驱动，须符合银监会/证监会相关标准\n"
            "- 决策链条长（IT→采购→合规→高层），周期6-18个月\n"
            "- 倾向选择有金融行业案例的供应商\n"
            "- 对运维外包接受度低，要求自有团队可维护\n"
            "- 预算相对充裕，但审批严格\n\n"
            "关键诉求：\n"
            "- 可用性（99.9999%，金融级）\n"
            "- 安全性（物理隔离、灾备）\n"
            "- 可审计性（运维日志完整）\n"
            "- 国产化替代趋势（信创要求）"
        ),
    },
    {
        "tier": 2,
        "source": "brain_downlink",
        "category": "customer_profiles",
        "title": "客户画像 — 工业制造企业",
        "content": (
            "典型客户：半导体工厂、汽车产线、制药企业\n\n"
            "决策特点：\n"
            "- 关注生产连续性，停电损失巨大（$10k-1M/小时）\n"
            "- 对物理环境耐受性要求高（粉尘、振动、温度）\n"
            "- 内部工程团队强，技术要求具体且专业\n"
            "- 倾向分阶段部署（先试点后推广）\n\n"
            "关键诉求：\n"
            "- 抗恶劣环境能力（IP防护等级、宽温工作）\n"
            "- 与现有电力系统无缝集成\n"
            "- 快速响应服务（4小时到场）\n"
            "- 备件供应保障（关键部件本地库存）"
        ),
    },
]


# ── Routes ────────────────────────────────────────────────────────

@router.get("")
async def list_knowledge(
    tier: int | None = Query(default=None, ge=1, le=3, description="Filter by tier"),
    category: str | None = Query(default=None, description="Filter by category"),
    q: str | None = Query(default=None, description="Search in title and content"),
    all: bool = Query(default=False, description="Include inactive entries"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[KnowledgeResponse]:
    """List knowledge entries for the current tenant.

    By default, only active entries are returned. Use ?all=true to include
    inactive (soft-deleted) entries. Supports optional filtering by tier,
    category, and free-text search (q).
    """
    stmt = select(KnowledgeEntry).where(
        KnowledgeEntry.tenant_id == current_user.tenant_id
    )

    if not all:
        stmt = stmt.where(KnowledgeEntry.is_active == True)

    if tier is not None:
        stmt = stmt.where(KnowledgeEntry.tier == tier)

    if category is not None:
        stmt = stmt.where(KnowledgeEntry.category == category)

    if q is not None:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                KnowledgeEntry.title.ilike(pattern),
                KnowledgeEntry.content.ilike(pattern),
            )
        )

    stmt = stmt.order_by(KnowledgeEntry.tier, KnowledgeEntry.category, KnowledgeEntry.created_at.desc())

    result = await db.execute(stmt)
    items = result.scalars().all()
    return [KnowledgeResponse.from_orm(item) for item in items]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_knowledge(
    body: KnowledgeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeResponse:
    """Create a new knowledge entry (user-created entries must be Tier 3).

    Tier 2 entries (source=brain_downlink) cannot be created by users.
    """
    # Users may only create Tier 3 entries
    if body.tier != 3:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Users may only create Tier 3 (company) knowledge entries",
        )

    # Explicitly block brain_downlink source from user creation
    if body.source == "brain_downlink":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="brain_downlink source is reserved for system-generated Tier 2 entries",
        )

    entry = KnowledgeEntry(
        tenant_id=current_user.tenant_id,
        tier=body.tier,
        category=body.category,
        title=body.title,
        content=body.content,
        source=body.source,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return KnowledgeResponse.from_orm(entry)


@router.patch("/{entry_id}")
async def patch_knowledge(
    entry_id: uuid.UUID,
    body: KnowledgeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeResponse:
    """Update an existing knowledge entry (tenant-scoped).

    Tier 2 entries (source=brain_downlink) cannot be edited by users.
    """
    result = await db.execute(
        select(KnowledgeEntry).where(
            KnowledgeEntry.id == entry_id,
            KnowledgeEntry.tenant_id == current_user.tenant_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge entry not found",
        )

    if entry.source == "brain_downlink":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tier 2 entries (brain_downlink source) cannot be edited",
        )

    if body.category is not None:
        entry.category = body.category
    if body.title is not None:
        entry.title = body.title
    if body.content is not None:
        entry.content = body.content
    if body.tier is not None:
        # Allow changing tier but still must be valid
        if body.tier not in (1, 2, 3):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Tier must be 1, 2, or 3",
            )
        entry.tier = body.tier
    if body.is_active is not None:
        entry.is_active = body.is_active

    await db.commit()
    await db.refresh(entry)
    return KnowledgeResponse.from_orm(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge(
    entry_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete or soft-delete a knowledge entry.

    - Tier 2 entries (brain_downlink) cannot be deleted.
    - Tier 3 entries are soft-deleted (is_active=False).
    - Tier 1 entries are hard-deleted.
    """
    result = await db.execute(
        select(KnowledgeEntry).where(
            KnowledgeEntry.id == entry_id,
            KnowledgeEntry.tenant_id == current_user.tenant_id,
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge entry not found",
        )

    if entry.tier == 2:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tier 2 entries (brain_downlink source) cannot be deleted",
        )

    if entry.tier == 3:
        # Soft-delete for company entries
        entry.is_active = False
        await db.commit()
    else:
        # Hard-delete for Tier 1 (global reference)
        await db.delete(entry)
        await db.commit()


@router.post("/seed", status_code=status.HTTP_201_CREATED)
async def seed_knowledge(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[KnowledgeResponse]:
    """Seed 12 default knowledge entries for the current tenant.

    Creates 5 Tier 1 (global reference) and 7 Tier 2 (industry knowledge)
    entries if the tenant has none. Idempotent — repeated calls are no-ops.
    """
    # Check if this tenant already has knowledge entries
    existing = await db.execute(
        select(KnowledgeEntry)
        .where(KnowledgeEntry.tenant_id == current_user.tenant_id)
        .limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        # Already seeded — return existing
        result = await db.execute(
            select(KnowledgeEntry)
            .where(KnowledgeEntry.tenant_id == current_user.tenant_id)
            .order_by(KnowledgeEntry.tier, KnowledgeEntry.category, KnowledgeEntry.created_at.desc())
        )
        return [KnowledgeResponse.from_orm(item) for item in result.scalars().all()]

    created: list[KnowledgeEntry] = []
    for tmpl in SEED_ENTRIES:
        entry = KnowledgeEntry(
            tenant_id=current_user.tenant_id,
            tier=tmpl["tier"],
            category=tmpl["category"],
            title=tmpl["title"],
            content=tmpl["content"],
            source=tmpl["source"],
        )
        db.add(entry)
        created.append(entry)

    await db.commit()
    for entry in created:
        await db.refresh(entry)

    return [KnowledgeResponse.from_orm(e) for e in created]
