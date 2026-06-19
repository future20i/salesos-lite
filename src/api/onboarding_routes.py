"""Onboarding wizard API — step tracking, channel setup."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.user import User
from src.models.tenant import Tenant
from src.auth import get_current_user

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


class OnboardingResponse(BaseModel):
    step: int
    steps: list[dict]


STEPS = [
    {"id": 0, "title": "欢迎加入 SalesOS Lite", "description": "你已获得 14 天全功能试用"},
    {
        "id": 1,
        "title": "配置邮件渠道",
        "description": "设置邮件转发，让客户邮件自动进入收件箱",
    },
    {
        "id": 2,
        "title": "嵌入 Web Chat",
        "description": "复制 JS 代码片段到你的官网，开始接收网站访客消息",
    },
    {
        "id": 3,
        "title": "邀请同事",
        "description": "发送邀请链接，让团队成员一起使用",
    },
    {
        "id": 4,
        "title": "设置完成",
        "description": "开始使用 SalesOS Lite 收件箱",
    },
]


@router.get("/state")
async def get_onboarding_state(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingResponse:
    result = await db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id)
    )
    tenant = result.scalar_one_or_none()
    step = tenant.onboarding_step if tenant else 0
    return OnboardingResponse(step=step, steps=STEPS)


class AdvanceOnboardingRequest(BaseModel):
    step: int


@router.post("/advance")
async def advance_onboarding(
    body: AdvanceOnboardingRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingResponse:
    if body.step < 0 or body.step > 4:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid step",
        )

    result = await db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id)
    )
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.onboarding_step = body.step
    await db.commit()

    return OnboardingResponse(step=tenant.onboarding_step, steps=STEPS)
