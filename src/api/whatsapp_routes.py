"""WhatsApp Cloud API webhook — receive and send WhatsApp messages.

Webhook verification + inbound message handling.
See: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import hashlib
import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.models.lead import Lead, Channel
from src.models.message import Message, MessageDirection
from src.models.ai_job import AIJob, AIJobStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


# ── Webhook Verification (GET) ───────────────────────────────────────
# WhatsApp sends a GET with hub.mode, hub.verify_token, hub.challenge.
# You configure the verify_token in Meta Developer Dashboard.

# Use env var for the verify token
import os

WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "salesos_lite_dev")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")


@router.get("/webhook")
async def whatsapp_verify(
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
):
    """Verify webhook for WhatsApp Cloud API."""
    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("WhatsApp webhook verified")
        return int(challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


# ── Inbound Messages (POST) ─────────────────────────────────────────

class WhatsAppWebhookPayload(BaseModel):
    object: str
    entry: list[dict]


@router.post("/webhook")
async def whatsapp_webhook(payload: WhatsAppWebhookPayload):
    """Receive inbound WhatsApp messages."""
    if payload.object != "whatsapp_business_account":
        return {"status": "ignored"}

    for entry in payload.entry:
        for change in entry.get("changes", []):
            if change.get("field") != "messages":
                continue

            value = change.get("value", {})
            metadata = value.get("metadata", {})
            phone_id = metadata.get("phone_number_id", "unknown")

            for msg in value.get("messages", []) or []:
                await _handle_inbound_message(msg, phone_id)

    return {"status": "received"}


async def _handle_inbound_message(msg: dict, phone_id: str):
    """Process a single inbound WhatsApp message."""
    msg_type = msg.get("type", "text")
    from_number = msg.get("from", "unknown")
    msg_id = msg.get("id", "")

    # Extract text content
    content = ""
    if msg_type == "text":
        content = msg.get("text", {}).get("body", "")
    elif msg_type == "image":
        caption = msg.get("image", {}).get("caption", "")
        content = caption or "[图片消息]"
    elif msg_type == "audio":
        content = "[语音消息]"
    else:
        content = f"[{msg_type} 消息]"

    if not content:
        return

    async with AsyncSessionLocal() as session:
        # Find or create lead by WhatsApp number
        result = await session.execute(
            select(Lead).where(
                Lead.channel == Channel.WHATSAPP,
                Lead.customer_name == from_number,
            )
        )
        lead = result.scalar_one_or_none()

        # Get tenant
        from src.models.tenant import Tenant
        tenant_result = await session.execute(select(Tenant).limit(1))
        tenant = tenant_result.scalar_one_or_none()

        if tenant is None:
            logger.warning("No tenant found for WhatsApp message")
            return

        if lead is None:
            lead = Lead(
                tenant_id=tenant.id,
                customer_name=from_number,
                channel=Channel.WHATSAPP,
            )
            session.add(lead)
            await session.flush()

        # Create message
        message = Message(
            tenant_id=tenant.id,
            lead_id=lead.id,
            content=content,
            direction=MessageDirection.INBOUND,
            sender="customer",
            channel=Channel.WHATSAPP,
            channel_message_id=msg_id,
        )
        session.add(message)
        await session.flush()

        # Enqueue AI job
        ai_job = AIJob(
            tenant_id=tenant.id,
            lead_id=lead.id,
            message_id=message.id,
            job_type="intent_grading",
            status=AIJobStatus.PENDING,
            tenant_tier="starter",
        )
        session.add(ai_job)

        await session.commit()

        logger.info(
            "WhatsApp message from %s processed (lead=%s)",
            from_number,
            lead.id,
        )
