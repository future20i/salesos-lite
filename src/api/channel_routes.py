"""Phase 4 — Channel adapter routes (Mailgun, etc.)."""

import json

from fastapi import APIRouter, Depends, HTTPException, Form, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import AsyncClient

from src.database import get_db

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.post("/mailgun/inbound")
async def mailgun_inbound(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Accepts Mailgun inbound webhook (form-encoded).

    Delegates to inbox/incoming to create lead + message.
    """
    try:
        form = await request.form()
        sender = form.get("sender", "")
        subject = form.get("subject", "")
        body_plain = form.get("body-plain", "")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid form data")

    if not sender or not body_plain:
        raise HTTPException(
            status_code=400,
            detail="Missing required fields: sender, body-plain",
        )

    # Extract customer name from email (everything before @)
    customer_name = sender.split("@")[0] if "@" in sender else sender

    # Delegate to inbox/incoming via internal HTTP call
    # Build the request URL based on the incoming host
    base_url = str(request.base_url).rstrip("/")

    async with AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/inbox/incoming",
            json={
                "customer_name": customer_name,
                "content": f"Subject: {subject}\n\n{body_plain}",
                "channel": "email",
                "channel_message_id": None,
            },
        )

    if resp.status_code != 201:
        raise HTTPException(
            status_code=502,
            detail=f"Inbox processing failed: {resp.text}",
        )

    data = resp.json()
    return {
        "status": "received",
        "lead_id": data["lead_id"],
        "message_id": data["message_id"],
    }
