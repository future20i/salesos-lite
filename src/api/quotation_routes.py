"""Quotation API — LLM-powered structured extraction from lead messages."""
import json
import logging
import os
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user
from src.database import get_db
from src.models.user import User
from src.models.lead import Lead
from src.models.message import Message
from src.models.quotation import Quotation

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/leads", tags=["quotations"])

LLM_API_KEY = os.getenv("LLM_API_KEY", os.getenv("DEEPSEEK_API_KEY", os.getenv("OPENAI_API_KEY", "")))
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

QUOTATION_PROMPT = """You are an extraction API for a foreign trade CRM. Extract structured quotation data from the conversation below.

Return ONLY valid JSON. No markdown, no explanation.

Fields to extract (use null if not found):
- product_name: the product being quoted (REQUIRED — use the best guess from context if not explicit)
- quantity: numeric quantity (e.g. 500, 2.5)
- unit: unit of measure (pcs, kg, ton, set, container, etc.)
- unit_price: price per unit as a number
- total: total order value as a number
- currency: ISO 4217 code (USD, EUR, CNY, etc.) — default "USD"
- validity_days: how many days the quote is valid (e.g. 30)
- incoterm: trade term (FOB, CIF, EXW, DDP, etc.)
- port: destination port or location
- payment_terms: payment method (e.g. "T/T 30% advance, 70% against B/L", "L/C at sight")
- notes: any additional context or remarks
- confidence: your confidence in the extraction (0.0–1.0)

Example output:
{"product_name":"N95 meltblown fabric","quantity":5,"unit":"ton","unit_price":8000,"total":40000,"currency":"USD","validity_days":15,"incoterm":"FOB","port":"Shanghai","payment_terms":"T/T 30% advance","notes":"Customer requested 3-layer BFE99 spec","confidence":0.85}

Conversation:
{context}

Extract the quotation:"""


def _build_context(messages: list[Message]) -> str:
    """Build conversation text from messages."""
    lines = []
    for m in messages:
        role = "Customer" if m.direction.value == "inbound" else "Agent"
        lines.append(f"{role}: {m.content}")
    return "\n".join(lines) if lines else "(no messages)"


async def _call_llm(prompt: str) -> dict:
    """Call LLM for quotation extraction. Returns parsed JSON dict."""
    if not LLM_API_KEY:
        return {"error": "LLM not configured"}

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {LLM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": "You are a JSON-only API. Always respond with valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 800,
                },
            )
            resp.raise_for_status()
        data = resp.json()
        raw = data["choices"][0]["message"]["content"].strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = lines[1:] if lines[0].startswith("```") else lines
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines)
        return json.loads(raw)
    except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
        logger.error("LLM extraction error: %s", exc)
        return {"error": str(exc)}


# ── Schemas ──────────────────────────────────────────────────────────

class QuotationOut(BaseModel):
    id: str
    lead_id: str
    product_name: str
    quantity: float | None = None
    unit: str | None = None
    unit_price: float | None = None
    total: float | None = None
    currency: str = "USD"
    validity_days: int | None = None
    incoterm: str | None = None
    port: str | None = None
    payment_terms: str | None = None
    notes: str | None = None
    confidence: float = 0.0
    created_at: str | None = None

    @classmethod
    def from_orm(cls, q: Quotation) -> "QuotationOut":
        return cls(
            id=str(q.id),
            lead_id=str(q.lead_id),
            product_name=q.product_name,
            quantity=q.quantity,
            unit=q.unit,
            unit_price=q.unit_price,
            total=q.total,
            currency=q.currency,
            validity_days=q.validity_days,
            incoterm=q.incoterm,
            port=q.port,
            payment_terms=q.payment_terms,
            notes=q.notes,
            confidence=q.confidence,
            created_at=str(q.created_at) if q.created_at else None,
        )


class ExtractQuotationResponse(BaseModel):
    status: str
    quotation: QuotationOut | None = None
    error: str | None = None


# ── Routes ───────────────────────────────────────────────────────────

@router.get("/{lead_id}/quotations")
async def list_quotations(
    lead_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[QuotationOut]:
    """List all extracted quotations for a lead."""
    result = await db.execute(
        select(Quotation)
        .where(
            Quotation.lead_id == lead_id,
            Quotation.tenant_id == current_user.tenant_id,
        )
        .order_by(Quotation.created_at.desc())
    )
    return [QuotationOut.from_orm(q) for q in result.scalars().all()]


@router.post("/{lead_id}/extract-quotation", status_code=status.HTTP_201_CREATED)
async def extract_quotation(
    lead_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExtractQuotationResponse:
    """Extract structured quotation from this lead's recent messages using LLM."""
    # Verify lead belongs to tenant
    lead_result = await db.execute(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.tenant_id == current_user.tenant_id,
        )
    )
    lead = lead_result.scalar_one_or_none()
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Fetch recent messages
    msg_result = await db.execute(
        select(Message)
        .where(Message.lead_id == lead_id)
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    messages = list(msg_result.scalars().all())
    messages.reverse()

    if not messages:
        raise HTTPException(status_code=400, detail="No messages to extract from")

    # Build context and call LLM
    context = _build_context(messages)
    extracted = await _call_llm(QUOTATION_PROMPT.format(context=context[:4000]))

    if "error" in extracted or "product_name" not in extracted:
        return ExtractQuotationResponse(
            status="failed",
            error=extracted.get("error", "No product_name found in extraction"),
        )

    # Find source message (last inbound message)
    last_inbound = next(
        (m for m in reversed(messages) if m.direction.value == "inbound"),
        messages[-1],
    )

    # Create quotation record
    quotation = Quotation(
        tenant_id=current_user.tenant_id,
        lead_id=lead_id,
        source_message_id=last_inbound.id,
        product_name=extracted.get("product_name", "Unknown"),
        quantity=extracted.get("quantity"),
        unit=extracted.get("unit"),
        unit_price=extracted.get("unit_price"),
        total=extracted.get("total"),
        currency=extracted.get("currency", "USD"),
        validity_days=extracted.get("validity_days"),
        incoterm=extracted.get("incoterm"),
        port=extracted.get("port"),
        payment_terms=extracted.get("payment_terms"),
        notes=extracted.get("notes"),
        confidence=float(extracted.get("confidence", 0.0)),
        raw_extraction=json.dumps(extracted),
    )
    db.add(quotation)

    # Update lead status to QUOTED if not already
    if lead.status.value != "quoted":
        from src.models.lead import LeadStatus
        lead.status = LeadStatus.QUOTED

    await db.commit()
    await db.refresh(quotation)

    logger.info("Quotation extracted for lead=%s: %s (confidence=%.2f)",
                lead_id, quotation.product_name, quotation.confidence)

    return ExtractQuotationResponse(
        status="ok",
        quotation=QuotationOut.from_orm(quotation),
    )


@router.delete("/quotations/{quotation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quotation(
    quotation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a quotation (tenant-scoped)."""
    result = await db.execute(
        select(Quotation).where(
            Quotation.id == quotation_id,
            Quotation.tenant_id == current_user.tenant_id,
        )
    )
    q = result.scalar_one_or_none()
    if q is None:
        raise HTTPException(status_code=404, detail="Quotation not found")
    await db.delete(q)
    await db.commit()
