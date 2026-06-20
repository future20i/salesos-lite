"""WhatsApp Cloud API webhook — receive and send WhatsApp messages.

Webhook verification + inbound message handling + outbound send.
See: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from httpx import AsyncClient
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user
from src.database import AsyncSessionLocal
from src.models.lead import Lead, Channel
from src.models.message import Message, MessageDirection
from src.models.ai_job import AIJob, AIJobStatus
from src.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])


# ── Webhook Verification (GET) ───────────────────────────────────────
# WhatsApp sends a GET with hub.mode, hub.verify_token, hub.challenge.
# You configure the verify_token in Meta Developer Dashboard.

# Use env var for the verify token
import os

WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "salesos_lite_dev")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_API_BASE = "https://graph.facebook.com/v18.0"


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


def _verify_signature(payload_bytes: bytes, signature_header: str | None) -> bool:
    """Verify X-Hub-Signature-256 against the request body using WHATSAPP_APP_SECRET."""
    if not WHATSAPP_APP_SECRET or not signature_header:
        return False
    expected_prefix = "sha256="
    if not signature_header.startswith(expected_prefix):
        return False
    received_sig = signature_header[len(expected_prefix):]
    computed_sig = hmac.new(
        WHATSAPP_APP_SECRET.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(computed_sig, received_sig)


# ── Outbound Send (POST) ─────────────────────────────────────────────


class SendMessageRequest(BaseModel):
    lead_id: str
    content: str
    type: str = "text"  # "text" or "template"


class SendMessageResponse(BaseModel):
    message_id: str
    wa_message_id: str


@router.post("/send", response_model=SendMessageResponse, status_code=status.HTTP_201_CREATED)
async def whatsapp_send(
    body: SendMessageRequest,
    current_user: User = Depends(get_current_user),
):
    """Send an outbound WhatsApp message via Cloud API."""
    lead_uuid = UUID(body.lead_id)

    if not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_ACCESS_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="WhatsApp integration not configured",
        )

    async with AsyncSessionLocal() as session:
        # Look up lead
        result = await session.execute(
            select(Lead).where(Lead.id == lead_uuid, Lead.tenant_id == current_user.tenant_id)
        )
        lead = result.scalar_one_or_none()
        if lead is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")

        to_number = lead.customer_name
        if lead.channel != Channel.WHATSAPP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Lead channel is {lead.channel.value}, not whatsapp",
            )

        # Build Cloud API payload
        wa_payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
        }
        if body.type == "text":
            wa_payload["type"] = "text"
            wa_payload["text"] = {"body": body.content}
        elif body.type == "template":
            wa_payload["type"] = "template"
            wa_payload["template"] = {"name": body.content}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported message type: {body.type}",
            )

        # Send to WhatsApp Cloud API
        url = f"{WHATSAPP_API_BASE}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
        async with AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                json=wa_payload,
                headers={
                    "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
                },
            )

        if resp.status_code != 200:
            logger.error(
                "WhatsApp API error: status=%s body=%s", resp.status_code, resp.text
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"WhatsApp API returned {resp.status_code}",
            )

        wa_result = resp.json()
        wa_message_id = (wa_result.get("messages") or [{}])[0].get("id", "")

        # Create outbound Message record
        message = Message(
            tenant_id=current_user.tenant_id,
            lead_id=lead.id,
            content=body.content,
            direction=MessageDirection.OUTBOUND,
            sender="agent",
            channel=Channel.WHATSAPP,
            channel_message_id=wa_message_id,
        )
        session.add(message)
        await session.flush()

        # Update lead last_activity_at
        lead.last_activity_at = datetime.now(timezone.utc)

        await session.commit()

        logger.info(
            "Outbound WhatsApp message sent to lead=%s wa_message_id=%s",
            lead.id,
            wa_message_id,
        )

        return SendMessageResponse(
            message_id=str(message.id),
            wa_message_id=wa_message_id,
        )


# ── Inbound Messages (POST) ─────────────────────────────────────────

class WhatsAppWebhookPayload(BaseModel):
    object: str
    entry: list[dict]


@router.post("/webhook")
async def whatsapp_webhook(
    request: Request,
    payload: WhatsAppWebhookPayload,
):
    """Receive inbound WhatsApp messages."""
    if payload.object != "whatsapp_business_account":
        return {"status": "ignored"}

    # Verify X-Hub-Signature-256
    raw_body = await request.body()
    sig_header = request.headers.get("x-hub-signature-256")
    if not _verify_signature(raw_body, sig_header):
        logger.warning("WhatsApp webhook signature verification failed")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

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
