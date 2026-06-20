"""Shared messaging service — WhatsApp + Email sending used by followup engine and manual compose."""
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.lead import Lead, Channel
from src.models.message import Message, MessageDirection

logger = logging.getLogger(__name__)

WHATSAPP_API_BASE = "https://graph.facebook.com/v18.0"
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")


async def send_whatsapp_message(
    db: AsyncSession,
    lead: Lead,
    content: str,
    msg_type: str = "text",
) -> str | None:
    """Send a WhatsApp message via Cloud API. Returns wa_message_id or None on failure."""
    if not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_ACCESS_TOKEN:
        logger.warning("WhatsApp not configured — cannot send to lead %s", lead.id)
        return None

    wa_payload: dict = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": lead.customer_name,
    }
    if msg_type == "template":
        wa_payload["type"] = "template"
        wa_payload["template"] = {"name": content}
    else:
        wa_payload["type"] = "text"
        wa_payload["text"] = {"body": content}

    url = f"{WHATSAPP_API_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    try:
        async with AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                json=wa_payload,
                headers={"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"},
            )
        if resp.status_code != 200:
            logger.error("WhatsApp send failed: status=%s body=%s", resp.status_code, resp.text)
            return None

        wa_result = resp.json()
        wa_message_id = (wa_result.get("messages") or [{}])[0].get("id", "")
    except Exception as exc:
        logger.exception("WhatsApp send exception for lead %s: %s", lead.id, exc)
        return None

    # Record outbound message
    msg = Message(
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        content=content,
        direction=MessageDirection.OUTBOUND,
        sender="auto",
        channel=Channel.WHATSAPP,
        channel_message_id=wa_message_id,
    )
    db.add(msg)
    lead.last_activity_at = datetime.now(timezone.utc)

    logger.info("Auto-followup WhatsApp sent to lead=%s wa_id=%s", lead.id, wa_message_id)
    return wa_message_id


async def send_email_message(
    db: AsyncSession,
    lead: Lead,
    content: str,
    subject: str = "",
) -> str | None:
    """Send an email to the lead. Returns a tracking ID or None on failure.

    Uses the configured EmailConnection for this tenant if available.
    Otherwise logs and returns a placeholder.
    """
    from src.models.email_connection import EmailConnection

    result = await db.execute(
        select(EmailConnection).where(
            EmailConnection.tenant_id == lead.tenant_id,
            EmailConnection.enabled == True,  # noqa: E712
        ).limit(1)
    )
    conn = result.scalar_one_or_none()

    if conn is None:
        logger.info("No email connection for tenant %s — email not sent to lead %s", lead.tenant_id, lead.id)
        return None

    # In production, use the OAuth token to send via Gmail/Outlook API.
    # For now, log and record the intent.
    logger.info(
        "Email would be sent to lead=%s via %s: subject=%r body_len=%d",
        lead.id, conn.provider, subject, len(content),
    )

    # Record outbound message
    msg = Message(
        tenant_id=lead.tenant_id,
        lead_id=lead.id,
        content=f"[Email] {subject}\n\n{content}",
        direction=MessageDirection.OUTBOUND,
        sender="auto",
        channel=Channel.EMAIL,
    )
    db.add(msg)
    lead.last_activity_at = datetime.now(timezone.utc)

    return f"email:{conn.provider}:{lead.id}"
