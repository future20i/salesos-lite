"""Canned Response API — CRUD + seed data for foreign trade templates."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.user import User
from src.models.canned_response import CannedResponse, ResponseCategory
from src.auth import get_current_user

router = APIRouter(prefix="/api/canned", tags=["canned"])


# ── Schemas ───────────────────────────────────────────────────────

class CannedResponseCreate(BaseModel):
    category: str
    title: str
    content: str


class CannedResponseUpdate(BaseModel):
    category: str | None = None
    title: str | None = None
    content: str | None = None


class CannedResponseOut(BaseModel):
    id: str
    tenant_id: str
    category: str
    title: str
    content: str
    created_at: str | None = None

    @classmethod
    def from_orm(cls, obj: CannedResponse) -> "CannedResponseOut":
        return cls(
            id=str(obj.id),
            tenant_id=str(obj.tenant_id),
            category=obj.category.value if isinstance(obj.category, ResponseCategory) else obj.category,
            title=obj.title,
            content=obj.content,
            created_at=str(obj.created_at) if obj.created_at else None,
        )


# ── Seed templates ────────────────────────────────────────────────

SEED_TEMPLATES: list[dict] = [
    # ── Inquiry Reply (询价回复) ──
    {
        "category": ResponseCategory.INQUIRY_REPLY,
        "title": "N95口罩询价标准回复",
        "content": "尊敬的客户，感谢您的询价！关于N95口罩（型号：KN95-501），"
        "我司出厂价为FOB上海USD 0.85/只，起订量10,000只，交期15-20天。"
        "如您需要更多技术参数或样品，请随时告知。期待合作！",
    },
    {
        "category": ResponseCategory.INQUIRY_REPLY,
        "title": "熔喷布FOB报价模板",
        "content": "您好，感谢询价！我司熔喷布（BFE≥99%）目前FOB宁波报价为USD 3.50/kg，"
        "最小起订量5吨，交期7-10个工作日。随附产品规格书和SGS检测报告。"
        "如需安排样品，请告知地址，我们将尽快寄出。",
    },
    # ── Quotation Followup (报价跟进) ──
    {
        "category": ResponseCategory.QUOTATION_FOLLOWUP,
        "title": "报价3天后跟进",
        "content": "您好！三天前我们为您提供了报价，不知您是否已审阅？"
        "如对价格、交期或技术细节有任何疑问，我随时为您解答。"
        "如有其他需求或需要调整方案，也请不吝告知。期待您的反馈！",
    },
    {
        "category": ResponseCategory.QUOTATION_FOLLOWUP,
        "title": "报价1周后跟进",
        "content": "您好！一周前发送的报价方案，想跟进一下您的评估进展。"
        "目前原材料价格有所波动，建议您尽早确认以便锁定当前价格。"
        "如需重新报价或修改方案，请随时联系，我们将第一时间为您处理。",
    },
    # ── Sample Followup (样品跟进) ──
    {
        "category": ResponseCategory.SAMPLE_FOLLOWUP,
        "title": "样品寄出后跟进",
        "content": "您好！样品已于昨日通过DHL寄出，快递单号：XXXXXXXXX，预计3-5个工作日抵达。"
        "请您收到后测试确认。如有任何质量问题或疑问，欢迎随时反馈。"
        "待样品确认后，我们将立即安排批量订单生产。",
    },
    {
        "category": ResponseCategory.SAMPLE_FOLLOWUP,
        "title": "样品收到后跟进",
        "content": "您好！请问样品是否已顺利收到？我们非常重视您的测试反馈，"
        "如有任何改进建议或定制需求，请随时告诉我们。"
        "如样品符合要求，我们将为您准备批量订单的合同和PI。期待您的回复！",
    },
    # ── Holiday Greeting (节日问候) ──
    {
        "category": ResponseCategory.HOLIDAY_GREETING,
        "title": "春节祝福",
        "content": "尊敬的客户，新春快乐！感谢您在过去一年中的信任与支持。"
        "值此新春佳节，祝愿您和您的家人身体健康、阖家幸福、事业蒸蒸日上！"
        "我司将于2月X日恢复生产，届时欢迎随时下单。新年新气象，期待与您共创辉煌！",
    },
    {
        "category": ResponseCategory.HOLIDAY_GREETING,
        "title": "圣诞新年祝福",
        "content": "Dear valued customers, Merry Christmas and Happy New Year! "
        "We sincerely appreciate your continued support throughout this year. "
        "May the holiday season bring you joy and prosperity. "
        "We look forward to serving you even better in the coming year. "
        "Warmest wishes from the SalesOS team!",
    },
    # ── Order Nudge (催单) ──
    {
        "category": ResponseCategory.ORDER_NUDGE,
        "title": "确认订单提醒",
        "content": "您好！贵司的报价方案已过期在即，当前原材料价格处于低位，"
        "建议您尽快确认订单以锁定最优价格。目前我司排产档期充足，"
        "确认后可于5个工作日内安排生产。如有任何疑虑，请随时沟通！",
    },
    {
        "category": ResponseCategory.ORDER_NUDGE,
        "title": "付款提醒",
        "content": "您好！贵司订单的PI已发送，烦请安排付款以便我们安排生产。"
        "当前交期排期紧张，越早付款越能确保如期交货。"
        "如发票信息需要修改或有其他问题，请第一时间告知。谢谢！",
    },
    # ── Revival (沉默客户激活) ──
    {
        "category": ResponseCategory.REVIVAL,
        "title": "3个月未联系激活",
        "content": "您好！好久不见，近期一切可好？我们注意到已有一段时间没有联系了。"
        "近期我司推出了新产品线，品质提升的同时价格更具竞争力，"
        "附上最新产品目录供您参考。如果您有兴趣，我们可以安排一次简短的产品介绍。",
    },
    {
        "category": ResponseCategory.REVIVAL,
        "title": "6个月未联系激活",
        "content": "尊敬的合作伙伴，许久未联系，希望您一切顺利！"
        "过去半年我们持续优化产品和服务，目前已有多个新产品上市。"
        "特此为您准备了一份专属优惠方案，希望能为您带来更多价值。"
        "如您有时间，期待与您再次沟通！",
    },
]


# ── Routes ────────────────────────────────────────────────────────

@router.get("")
async def list_canned(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CannedResponseOut]:
    """List all canned responses for the current tenant."""
    result = await db.execute(
        select(CannedResponse)
        .where(CannedResponse.tenant_id == current_user.tenant_id)
        .order_by(CannedResponse.created_at.desc())
    )
    items = result.scalars().all()
    return [CannedResponseOut.from_orm(item) for item in items]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_canned(
    body: CannedResponseCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CannedResponseOut:
    """Create a new canned response for the current tenant."""
    try:
        category = ResponseCategory(body.category)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid category '{body.category}'. "
                   f"Must be one of: {[c.value for c in ResponseCategory]}",
        )

    canned = CannedResponse(
        tenant_id=current_user.tenant_id,
        category=category,
        title=body.title,
        content=body.content,
    )
    db.add(canned)
    await db.commit()
    await db.refresh(canned)
    return CannedResponseOut.from_orm(canned)


@router.put("/{canned_id}")
async def update_canned(
    canned_id: uuid.UUID,
    body: CannedResponseUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CannedResponseOut:
    """Update an existing canned response (tenant-scoped)."""
    result = await db.execute(
        select(CannedResponse).where(
            CannedResponse.id == canned_id,
            CannedResponse.tenant_id == current_user.tenant_id,
        )
    )
    canned = result.scalar_one_or_none()
    if canned is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canned response not found",
        )

    if body.category is not None:
        try:
            canned.category = ResponseCategory(body.category)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid category '{body.category}'",
            )
    if body.title is not None:
        canned.title = body.title
    if body.content is not None:
        canned.content = body.content

    await db.commit()
    await db.refresh(canned)
    return CannedResponseOut.from_orm(canned)


@router.delete("/{canned_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_canned(
    canned_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a canned response (tenant-scoped)."""
    result = await db.execute(
        select(CannedResponse).where(
            CannedResponse.id == canned_id,
            CannedResponse.tenant_id == current_user.tenant_id,
        )
    )
    canned = result.scalar_one_or_none()
    if canned is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canned response not found",
        )

    await db.delete(canned)
    await db.commit()


@router.post("/seed", status_code=status.HTTP_201_CREATED)
async def seed_canned(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CannedResponseOut]:
    """Seed 12 default foreign trade templates for the current tenant.

    If templates for the tenant already exist, this is a no-op to
    avoid duplicating seed data on repeated calls.
    """
    # Check if this tenant already has canned responses
    existing = await db.execute(
        select(CannedResponse).where(
            CannedResponse.tenant_id == current_user.tenant_id
        ).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        # Already seeded — return existing
        result = await db.execute(
            select(CannedResponse)
            .where(CannedResponse.tenant_id == current_user.tenant_id)
            .order_by(CannedResponse.created_at.desc())
        )
        return [CannedResponseOut.from_orm(item) for item in result.scalars().all()]

    created: list[CannedResponse] = []
    for tmpl in SEED_TEMPLATES:
        canned = CannedResponse(
            tenant_id=current_user.tenant_id,
            category=tmpl["category"],
            title=tmpl["title"],
            content=tmpl["content"],
        )
        db.add(canned)
        created.append(canned)

    await db.commit()
    for canned in created:
        await db.refresh(canned)

    return [CannedResponseOut.from_orm(c) for c in created]
