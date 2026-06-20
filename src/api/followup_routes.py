"""Follow-up Rules API — CRUD + manual trigger for auto follow-up engine."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db, AsyncSessionLocal
from src.models.user import User
from src.models.lead import Lead, LeadStatus, Intent
from src.models.message import Message, MessageDirection
from src.models.followup_rule import (
    FollowupRule,
    FollowupLog,
    TriggerType,
    ActionType,
)
from src.models.canned_response import CannedResponse, ResponseCategory
from src.auth import get_current_user

router = APIRouter(prefix="/api/followup", tags=["followup"])


# ── Schemas ────────────────────────────────────────────────────────

class FollowupRuleCreate(BaseModel):
    name: str
    trigger_type: str
    trigger_value: str
    action_type: str
    action_value: str
    enabled: bool = True


class FollowupRuleUpdate(BaseModel):
    name: str | None = None
    trigger_type: str | None = None
    trigger_value: str | None = None
    action_type: str | None = None
    action_value: str | None = None
    enabled: bool | None = None


class FollowupRuleOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    trigger_type: str
    trigger_value: str
    action_type: str
    action_value: str
    enabled: bool
    created_at: str | None = None

    @classmethod
    def from_orm(cls, obj: FollowupRule) -> "FollowupRuleOut":
        return cls(
            id=str(obj.id),
            tenant_id=str(obj.tenant_id),
            name=obj.name,
            trigger_type=obj.trigger_type.value if isinstance(obj.trigger_type, TriggerType) else obj.trigger_type,
            trigger_value=obj.trigger_value,
            action_type=obj.action_type.value if isinstance(obj.action_type, ActionType) else obj.action_type,
            action_value=obj.action_value,
            enabled=obj.enabled,
            created_at=str(obj.created_at) if obj.created_at else None,
        )


class FollowupLogOut(BaseModel):
    id: str
    rule_id: str
    tenant_id: str
    lead_id: str
    action_type: str
    action_value: str
    result: str | None = None
    success: bool
    created_at: str | None = None

    @classmethod
    def from_orm(cls, obj: FollowupLog) -> "FollowupLogOut":
        return cls(
            id=str(obj.id),
            rule_id=str(obj.rule_id),
            tenant_id=str(obj.tenant_id),
            lead_id=str(obj.lead_id),
            action_type=obj.action_type.value if isinstance(obj.action_type, ActionType) else obj.action_type,
            action_value=obj.action_value,
            result=obj.result,
            success=obj.success,
            created_at=str(obj.created_at) if obj.created_at else None,
        )


# ── Routes ─────────────────────────────────────────────────────────

@router.get("/rules")
async def list_rules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FollowupRuleOut]:
    """List all follow-up rules for the current tenant."""
    result = await db.execute(
        select(FollowupRule)
        .where(FollowupRule.tenant_id == current_user.tenant_id)
        .order_by(FollowupRule.created_at.desc())
    )
    return [FollowupRuleOut.from_orm(item) for item in result.scalars().all()]


@router.post("/rules", status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: FollowupRuleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FollowupRuleOut:
    """Create a new follow-up rule for the current tenant."""
    # Validate trigger_type
    try:
        trigger_type = TriggerType(body.trigger_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid trigger_type '{body.trigger_type}'. "
                   f"Must be one of: {[t.value for t in TriggerType]}",
        )
    # Validate action_type
    try:
        action_type = ActionType(body.action_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid action_type '{body.action_type}'. "
                   f"Must be one of: {[a.value for a in ActionType]}",
        )

    rule = FollowupRule(
        tenant_id=current_user.tenant_id,
        name=body.name,
        trigger_type=trigger_type,
        trigger_value=body.trigger_value,
        action_type=action_type,
        action_value=body.action_value,
        enabled=body.enabled,
    )
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    return FollowupRuleOut.from_orm(rule)


@router.put("/rules/{rule_id}")
async def update_rule(
    rule_id: uuid.UUID,
    body: FollowupRuleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FollowupRuleOut:
    """Update an existing follow-up rule (tenant-scoped)."""
    result = await db.execute(
        select(FollowupRule).where(
            FollowupRule.id == rule_id,
            FollowupRule.tenant_id == current_user.tenant_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Follow-up rule not found",
        )

    if body.name is not None:
        rule.name = body.name
    if body.trigger_type is not None:
        try:
            rule.trigger_type = TriggerType(body.trigger_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid trigger_type '{body.trigger_type}'",
            )
    if body.trigger_value is not None:
        rule.trigger_value = body.trigger_value
    if body.action_type is not None:
        try:
            rule.action_type = ActionType(body.action_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid action_type '{body.action_type}'",
            )
    if body.action_value is not None:
        rule.action_value = body.action_value
    if body.enabled is not None:
        rule.enabled = body.enabled

    await db.commit()
    await db.refresh(rule)
    return FollowupRuleOut.from_orm(rule)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a follow-up rule (tenant-scoped)."""
    result = await db.execute(
        select(FollowupRule).where(
            FollowupRule.id == rule_id,
            FollowupRule.tenant_id == current_user.tenant_id,
        )
    )
    rule = result.scalar_one_or_none()
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Follow-up rule not found",
        )
    await db.delete(rule)
    await db.commit()


@router.get("/logs")
async def list_logs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
) -> list[FollowupLogOut]:
    """List recent follow-up execution logs for the current tenant."""
    result = await db.execute(
        select(FollowupLog)
        .where(FollowupLog.tenant_id == current_user.tenant_id)
        .order_by(FollowupLog.created_at.desc())
        .limit(limit)
    )
    return [FollowupLogOut.from_orm(item) for item in result.scalars().all()]


# ── Manual trigger (for testing) ──────────────────────────────────

@router.post("/run")
async def manual_run(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually trigger rule evaluation for the current tenant."""
    logs = await evaluate_rules_for_tenant(db, current_user.tenant_id)
    return {"status": "ok", "rules_evaluated": len(logs)}


# ── Engine logic ───────────────────────────────────────────────────

async def evaluate_rules_for_tenant(
    db: AsyncSession, tenant_id: uuid.UUID
) -> list[FollowupLog]:
    """Evaluate all enabled follow-up rules for a single tenant.

    Returns the list of FollowupLog entries that were created.
    """
    result = await db.execute(
        select(FollowupRule).where(
            FollowupRule.tenant_id == tenant_id,
            FollowupRule.enabled == True,  # noqa: E712
        )
    )
    rules = result.scalars().all()

    now = datetime.now(timezone.utc)
    created_logs: list[FollowupLog] = []

    for rule in rules:
        try:
            matching_leads = await _find_matching_leads(
                db, tenant_id, rule, now
            )
        except Exception:
            # If a single rule's query fails, skip it gracefully
            continue

        for lead in matching_leads:
            # Guard: skip if this rule already fired for this lead recently
            already_fired = await db.execute(
                select(FollowupLog).where(
                    FollowupLog.rule_id == rule.id,
                    FollowupLog.lead_id == lead.id,
                    FollowupLog.created_at
                    > now - timedelta(hours=24),
                ).limit(1)
            )
            if already_fired.scalar_one_or_none() is not None:
                continue

            try:
                result_text = await _execute_action(
                    db, lead, rule, now
                )
                success = True
            except Exception as exc:
                result_text = str(exc)
                success = False

            log = FollowupLog(
                rule_id=rule.id,
                tenant_id=tenant_id,
                lead_id=lead.id,
                action_type=rule.action_type,
                action_value=rule.action_value,
                result=result_text,
                success=success,
            )
            db.add(log)
            created_logs.append(log)

    if created_logs:
        await db.commit()
        for log in created_logs:
            await db.refresh(log)

    return created_logs


async def _find_matching_leads(
    db: AsyncSession, tenant_id: uuid.UUID, rule: FollowupRule, now: datetime
) -> list[Lead]:
    """Return leads matching the given rule's trigger condition."""
    if rule.trigger_type == TriggerType.LEAD_INTENT:
        # trigger_value should be e.g. "hot", "warm", "cold", "dormant"
        try:
            intent = Intent(rule.trigger_value)
        except ValueError:
            return []
        result = await db.execute(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.intent == intent,
                Lead.status != LeadStatus.CLOSED,
            )
        )
        return list(result.scalars().all())

    elif rule.trigger_type == TriggerType.TIME_SINCE_CONTACT:
        # trigger_value is "48h", "72h", "168h" etc
        hours = _parse_hours(rule.trigger_value)
        if hours is None:
            return []
        cutoff = now - timedelta(hours=hours)

        # Subquery: find the latest message time per lead
        from sqlalchemy import func as sa_func
        latest_msg_subq = (
            select(
                Message.lead_id,
                sa_func.max(Message.created_at).label("last_contact"),
            )
            .where(Message.tenant_id == tenant_id)
            .group_by(Message.lead_id)
            .subquery()
        )

        result = await db.execute(
            select(Lead)
            .outerjoin(
                latest_msg_subq,
                Lead.id == latest_msg_subq.c.lead_id,
            )
            .where(
                Lead.tenant_id == tenant_id,
                Lead.status != LeadStatus.CLOSED,
                # No messages at all, or last message before cutoff
                sa_func.coalesce(
                    latest_msg_subq.c.last_contact,
                    Lead.created_at,
                )
                < cutoff,
            )
        )
        return list(result.scalars().all())

    elif rule.trigger_type == TriggerType.TIME_SINCE_STATUS:
        # trigger_value is "48h", "72h" etc — time since last status change
        hours = _parse_hours(rule.trigger_value)
        if hours is None:
            return []
        cutoff = now - timedelta(hours=hours)

        # Use last_activity_at as a proxy for status-change time
        result = await db.execute(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.status != LeadStatus.CLOSED,
                Lead.last_activity_at < cutoff,
            )
        )
        return list(result.scalars().all())

    return []


async def _execute_action(
    db: AsyncSession, lead: Lead, rule: FollowupRule, now: datetime
) -> str:
    """Execute the action of a rule against a lead and return a result string."""
    if rule.action_type == ActionType.SEND_TEMPLATE:
        # Find a canned response matching the action_value (category)
        try:
            category = ResponseCategory(rule.action_value)
        except ValueError:
            category = None

        if category:
            tmpl_result = await db.execute(
                select(CannedResponse)
                .where(
                    CannedResponse.tenant_id == lead.tenant_id,
                    CannedResponse.category == category,
                )
                .limit(1)
            )
            template = tmpl_result.scalar_one_or_none()
            if template:
                return f"Would send template '{template.title}' to lead {lead.id}"
            else:
                return f"No template found for category '{rule.action_value}'"
        else:
            # Try by template ID directly
            return f"Would send template '{rule.action_value}' to lead {lead.id}"

    elif rule.action_type == ActionType.SEND_AI_REPLY:
        return f"Would generate AI reply for lead {lead.id} using prompt '{rule.action_value}'"

    elif rule.action_type == ActionType.ASSIGN_TO:
        # action_value is a user_id
        lead.assigned_to = uuid.UUID(rule.action_value) if rule.action_value else None
        return f"Assigned lead {lead.id} to user {rule.action_value}"

    return f"Unknown action type: {rule.action_type}"


def _parse_hours(value: str) -> int | None:
    """Parse strings like '48h', '72h', '168h' into hours as int."""
    value = value.strip().lower()
    if value.endswith("h"):
        try:
            return int(value[:-1])
        except ValueError:
            return None
    try:
        return int(value)
    except ValueError:
        return None


# ── Seed defaults ──────────────────────────────────────────────────

SEED_RULES: list[dict] = [
    {
        "name": "48h no reply → send revival template",
        "trigger_type": TriggerType.TIME_SINCE_CONTACT,
        "trigger_value": "48h",
        "action_type": ActionType.SEND_TEMPLATE,
        "action_value": ResponseCategory.REVIVAL.value,
    },
    {
        "name": "Hot lead → assign to manager",
        "trigger_type": TriggerType.LEAD_INTENT,
        "trigger_value": "hot",
        "action_type": ActionType.ASSIGN_TO,
        "action_value": "",  # placeholder — no default manager
    },
    {
        "name": "7d no activity → send order nudge",
        "trigger_type": TriggerType.TIME_SINCE_CONTACT,
        "trigger_value": "168h",
        "action_type": ActionType.SEND_TEMPLATE,
        "action_value": ResponseCategory.ORDER_NUDGE.value,
    },
]


async def seed_default_rules(db: AsyncSession) -> None:
    """Seed 3 default follow-up rules for all tenants that have none yet."""
    from src.models.tenant import Tenant

    tenant_result = await db.execute(select(Tenant))
    tenants = tenant_result.scalars().all()

    for tenant in tenants:
        # Check if this tenant already has rules
        existing = await db.execute(
            select(FollowupRule)
            .where(FollowupRule.tenant_id == tenant.id)
            .limit(1)
        )
        if existing.scalar_one_or_none() is not None:
            continue

        for rule_data in SEED_RULES:
            rule = FollowupRule(
                tenant_id=tenant.id,
                name=rule_data["name"],
                trigger_type=rule_data["trigger_type"],
                trigger_value=rule_data["trigger_value"],
                action_type=rule_data["action_type"],
                action_value=rule_data["action_value"],
                enabled=True,
            )
            db.add(rule)

    await db.commit()


async def followup_evaluation_loop(interval_seconds: int = 60) -> None:
    """Background loop: evaluate follow-up rules for all tenants periodically."""
    import asyncio, logging
    _log = logging.getLogger(__name__)
    while True:
        try:
            async with AsyncSessionLocal() as _db:
                from src.models.tenant import Tenant
                result = await _db.execute(select(Tenant))
                tenants = result.scalars().all()
                total = 0
                for t in tenants:
                    logs = await evaluate_rules_for_tenant(_db, t.id)
                    total += len(logs)
                if total:
                    _log.info("Followup: executed %d actions across %d tenants", total, len(tenants))
        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("Followup evaluation loop error")
        await asyncio.sleep(interval_seconds)
