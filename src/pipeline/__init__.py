"""Silence check background loop — periodic scan of active opportunities."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.models import Opportunity, OpportunityStage, Message, MessageDirection, FollowupEvent

logger = logging.getLogger(__name__)

# Days without inbound reply before generating a silence alert
# Per-stage thresholds (defaults, tenant-configurable later)
SILENCE_THRESHOLDS: dict[str, int] = {
    "technical_exchange": 14,
    "quotation_negotiation": 7,
    "contract": 5,
}
DEFAULT_THRESHOLD = 14


async def check_silent_opportunities() -> int:
    """Scan all active opportunities for silence (no inbound message from customer).

    Active = not won/lost/shelved.
    For each active opportunity, find the most recent inbound message timestamp.
    If it exceeds the per-stage threshold, create a silence_alert FollowupEvent
    for the oldest pending followup_item (or a generic alert if none).

    Returns the number of alerts generated.
    """
    alerts = 0
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        # Find active opportunities
        active_stages = [
            OpportunityStage.LEAD_VALIDATION,
            OpportunityStage.NEEDS_CONFIRMATION,
            OpportunityStage.TECHNICAL_EXCHANGE,
            OpportunityStage.QUOTATION_NEGOTIATION,
            OpportunityStage.CONTRACT,
        ]

        result = await session.execute(
            select(Opportunity).where(Opportunity.stage.in_(active_stages))
        )
        opportunities = result.scalars().all()

        if not opportunities:
            return 0

        for opp in opportunities:
            threshold = SILENCE_THRESHOLDS.get(opp.stage.value if hasattr(opp.stage, 'value') else str(opp.stage), DEFAULT_THRESHOLD)

            # Find last inbound message from related lead
            if opp.lead_id:
                msg_result = await session.execute(
                    select(Message)
                    .where(
                        Message.lead_id == opp.lead_id,
                        Message.direction == MessageDirection.INBOUND,
                    )
                    .order_by(Message.created_at.desc())
                    .limit(1)
                )
                last_msg = msg_result.scalar_one_or_none()
            else:
                last_msg = None

            days_silent = None
            if last_msg:
                delta = now - last_msg.created_at.replace(tzinfo=timezone.utc)
                days_silent = delta.days
            elif opp.created_at:
                delta = now - opp.created_at.replace(tzinfo=timezone.utc)
                days_silent = delta.days
            else:
                continue

            if days_silent >= threshold:
                # Only create alerts for opportunities with followup items
                from src.models.followup import FollowupItem
                fu_result = await session.execute(
                    select(FollowupItem)
                    .where(FollowupItem.opportunity_id == opp.id)
                    .order_by(FollowupItem.created_at.asc())
                    .limit(1)
                )
                followup = fu_result.scalar_one_or_none()
                if followup is None:
                    continue

                event = FollowupEvent(
                    followup_id=followup.id,
                    kind="silence_alert",
                    payload={
                        "opportunity_id": str(opp.id),
                        "days_silent": days_silent,
                        "threshold": threshold,
                        "stage": opp.stage.value if hasattr(opp.stage, 'value') else str(opp.stage),
                        "last_inbound_at": last_msg.created_at.isoformat() if last_msg else None,
                    },
                )
                session.add(event)
                alerts += 1

        if alerts > 0:
            await session.commit()
            logger.info("Generated %d silence alerts", alerts)

    return alerts


async def silence_check_loop(interval_seconds: float = 3600.0) -> None:
    """Run silence check periodically.

    Parameters
    ----------
    interval_seconds : float
        Seconds between scans. Default: 3600 (1 hour).
    """
    logger.info("Silence check loop started (interval=%ds)", interval_seconds)
    while True:
        try:
            alerts = await check_silent_opportunities()
            if alerts:
                logger.info("Silence check: %d alerts", alerts)
        except Exception:
            logger.exception("Silence check failed")
        await asyncio.sleep(interval_seconds)
