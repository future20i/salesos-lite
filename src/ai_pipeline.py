"""
AI Pipeline — job polling loop.

Provides two main entry points:

* ``poll_and_process()`` — an async loop that repeatedly claims the next
  pending ``AIJob`` (using ``SKIP LOCKED``), processes it, and marks it done.
* ``recover_stale_jobs()`` — run as a periodic maintenance task; resets any
  ``PROCESSING`` jobs whose ``locked_at`` is older than 5 minutes back to
  ``PENDING``.

Phase 5 (M1) placeholder behaviour
-----------------------------------
The LLM call is stubbed: it simply sets ``intent="cold"`` on the associated
lead and marks the job as ``DONE``.  A real LLM client will be wired in
during M3.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database import AsyncSessionLocal
from src.models import AIJob, AIJobStatus, Lead, Intent, Message
from src.sanitize import sanitize

logger = logging.getLogger(__name__)

# ── rate-limiting counter (global, simplified for M1) ──────────────────────
_jobs_this_minute: int = 0
_last_reset: datetime | None = None

TIER_LIMITS: dict[str, int] = {
    "starter": 5,
    "growth": 20,
    "pro": 60,
}

STALE_TIMEOUT_MINUTES = 5


# ── helpers ────────────────────────────────────────────────────────────────

def _check_rate_limit(tier: str) -> bool:
    """Return ``True`` if a job for *tier* is allowed right now."""
    global _jobs_this_minute, _last_reset
    now = datetime.now(timezone.utc)
    if _last_reset is None or (now - _last_reset).total_seconds() >= 60:
        _jobs_this_minute = 0
        _last_reset = now
    limit = TIER_LIMITS.get(tier, 5)
    if _jobs_this_minute >= limit:
        logger.warning("Rate limit hit for tier '%s' (%d/min)", tier, limit)
        return False
    _jobs_this_minute += 1
    return True


async def recover_stale_jobs() -> int:
    """Reset ``PROCESSING`` jobs locked >5 minutes back to ``PENDING``.

    Returns the number of jobs recovered.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_TIMEOUT_MINUTES)
    async with AsyncSessionLocal() as session:
        stmt = (
            update(AIJob)
            .where(
                and_(
                    AIJob.status == AIJobStatus.PROCESSING,
                    AIJob.locked_at < cutoff,
                )
            )
            .values(
                status=AIJobStatus.PENDING,
                locked_at=None,
            )
            .returning(AIJob.id)
        )
        result = await session.execute(stmt)
        await session.commit()
        recovered = len(result.fetchall())
        if recovered:
            logger.info("Recovered %d stale AI jobs", recovered)
        return recovered


async def poll_and_process(
    interval_seconds: float = 2.0,
    max_iterations: int | None = None,
) -> None:
    """Main polling loop.

    Continuously claims and processes pending ``AIJob`` rows until
    *max_iterations* is reached (``None`` = run forever).

    Parameters
    ----------
    interval_seconds : float
        Sleep between iterations when no job is available.
    max_iterations : int | None
        Maximum loop iterations (for testing). ``None`` = run indefinitely.
    """
    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        iteration += 1

        try:
            await recover_stale_jobs()
            job = await _claim_next_job()
        except Exception:
            logger.exception("Error during job claim / stale recovery")
            await asyncio.sleep(interval_seconds)
            continue

        if job is None:
            await asyncio.sleep(interval_seconds)
            continue

        try:
            await _process_job(job)
        except Exception:
            logger.exception("Failed to process AI job %s", job.id)
            await _mark_failed(job.id)

    logger.info("poll_and_process finished after %d iterations", iteration)


# ── internal implementation ────────────────────────────────────────────────

async def _claim_next_job() -> AIJob | None:
    """Claim the next pending job with ``SKIP LOCKED``."""
    async with AsyncSessionLocal() as session:
        # Select one pending job
        stmt = (
            select(AIJob)
            .where(AIJob.status == AIJobStatus.PENDING)
            .order_by(AIJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(stmt)
        job = result.scalar_one_or_none()
        if job is None:
            return None

        # Mark PROCESSING with locked_at
        now = datetime.now(timezone.utc)
        stmt_update = (
            update(AIJob)
            .where(AIJob.id == job.id)
            .values(
                status=AIJobStatus.PROCESSING,
                locked_at=now,
            )
        )
        await session.execute(stmt_update)
        await session.commit()

        # Re-fetch to get updated state
        await session.refresh(job)
        return job


async def _process_job(job: AIJob) -> None:
    """Execute the AI job pipeline for *job*."""
    if not _check_rate_limit(job.tenant_tier):
        logger.info("Rate-limited: skipping job %s (tier=%s)", job.id, job.tenant_tier)
        # Leave it in PROCESSING — recover_stale_jobs will re-queue it later
        return

    async with AsyncSessionLocal() as session:
        # Fetch the message
        msg_stmt = select(Message).where(Message.id == job.message_id)
        msg_result = await session.execute(msg_stmt)
        message: Message | None = msg_result.scalar_one_or_none()
        if message is None:
            logger.warning("Message %s not found for job %s", job.message_id, job.id)
            await _mark_failed(job.id)
            return

        # ── Sanitize ──
        sanitized_text, mapping = sanitize(message.content)
        logger.debug(
            "Sanitized message %s: %d placeholders applied",
            message.id,
            sum(len(v) for v in mapping.values()),
        )

        # ── LLM call placeholder (M1) ──
        # In M3 this will actually call an LLM with sanitized_text.
        # For now, just set intent="cold" on the lead.
        lead_stmt = select(Lead).where(Lead.id == job.lead_id)
        lead_result = await session.execute(lead_stmt)
        lead: Lead | None = lead_result.scalar_one_or_none()
        if lead is None:
            logger.warning("Lead %s not found for job %s", job.lead_id, job.id)
            await _mark_failed(job.id)
            return

        # Desanitize before persisting (not strictly needed for M1 placeholder
        # since we don't pass anything back, but keeps the pattern correct).
        desanitized_text = _desanitize_llm_output(sanitized_text, mapping)

        lead.intent = Intent.COLD

        # ── Mark job DONE ──
        update_stmt = (
            update(AIJob)
            .where(AIJob.id == job.id)
            .values(
                status=AIJobStatus.DONE,
                result=desanitized_text,
                locked_at=None,
            )
        )
        await session.execute(update_stmt)
        await session.commit()

        logger.info(
            "Processed AI job %s (lead=%s, intent=cold)",
            job.id,
            job.lead_id,
        )


async def _mark_failed(job_id) -> None:
    """Mark an AI job as FAILED."""
    async with AsyncSessionLocal() as session:
        stmt = (
            update(AIJob)
            .where(AIJob.id == job_id)
            .values(
                status=AIJobStatus.FAILED,
                locked_at=None,
            )
        )
        await session.execute(stmt)
        await session.commit()


def _desanitize_llm_output(text: str, mapping: dict) -> str:
    """Restore original PII in LLM output using the sanitize module.

    For M1 the LLM just returns the sanitized text unchanged, so we
    run desanitize on whatever we have.  In M3 this will also merge
    any newly extracted entities.
    """
    from src.sanitize import desanitize as _desanitize
    return _desanitize(text, mapping)
