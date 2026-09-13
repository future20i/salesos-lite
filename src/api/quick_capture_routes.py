"""QuickCapture API — submit text/voice notes, AI parse, create followups.

POST   /api/quick-capture          — create capture from text
POST   /api/quick-capture/voice    — create capture from voice transcript
GET    /api/quick-capture           — list captures
GET    /api/quick-capture/{id}      — get capture detail
POST   /api/quick-capture/{id}/process — AI parse + create followups
DELETE /api/quick-capture/{id}      — delete capture
"""

import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.auth import get_current_user
from src.models.user import User
from src.models.opportunity import Opportunity
from src.models.followup import FollowupItem, FollowupStatus, ReviewLevel

router = APIRouter(prefix="/api/quick-capture", tags=["quick-capture"])

logger = logging.getLogger(__name__)


# ── Schemas ─────────────────────────────────────────────────────────────────

class QuickCaptureIn(BaseModel):
    raw_text: str = Field(..., min_length=1, max_length=5000)
    source_type: str = "text"  # text / voice
    customer_hint: str | None = None
    opportunity_hint: str | None = None


class QuickCaptureOut(BaseModel):
    id: str
    source_type: str
    raw_text: str
    customer_hint: str | None
    opportunity_hint: str | None
    status: str
    parsed: dict | None
    followup_ids: list | None
    created_at: str


# ── Helpers ─────────────────────────────────────────────────────────────────

def _parse_fallback(text: str, hint: str | None = None) -> dict:
    """Regex-based fallback when LLM is unavailable."""
    import re

    # Try to extract customer name
    customer = hint
    if not customer:
        m = re.search(r'(?:客户|联系人|拜访)[：:]\s*([^\n，,。]{2,20})', text)
        if m:
            customer = m.group(1).strip()

    # Extract action items (lines starting with - * • or numbered, or action keywords)
    items = []
    for line in text.split("\n"):
        line = line.strip()
        if not line: continue
        # Dash/star/bullet prefix: "- ", "* ", "• ", "1. ", "1) "
        if re.match(r'^[-*•]\s', line) and len(line) > 5:
            items.append({"title": re.sub(r'^[-*•]\s*', '', line), "priority": 1})
        elif re.match(r'^\d+[.)]\s', line) and len(line) > 5:
            items.append({"title": re.sub(r'^\d+[.)]\s*', '', line), "priority": 1})
        elif line.startswith(("需要", "跟进", "发送", "确认", "准备", "联系", "安排", "提供", "要求")):
            items.append({"title": line, "priority": 2})

    # Extract dates
    dates = re.findall(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日', text)

    # Extract products
    products = re.findall(r'[A-Z]{2,}-\d{3,}|[A-Z][a-z]+\s*\d{3,}', text)

    return {
        "summary": text[:100] + ("…" if len(text) > 100 else ""),
        "customer_match": customer,
        "action_items": items[:5] if items else [{"title": "跟进本次沟通内容", "priority": 1}],
        "dates_mentioned": dates[:3],
        "products_mentioned": products[:5],
        "sentiment": "neutral",
    }


async def _ai_parse(text: str, hint: str | None = None) -> dict:
    """Use LLM to parse quick capture text into structured data."""
    try:
        from src.llm_client import llm_complete
        from src.intel_engine import _safe_llm_json

        prompt = f"""Parse this sales meeting/call note into structured JSON. Extract:

1. A one-line Chinese summary (max 30 chars)
2. Customer name mentioned (or null)
3. Action items as list of {{"title": "...", "priority": 1-3}} (3=urgent)
4. Dates mentioned (YYYY-MM-DD format if possible)
5. Products/specifications mentioned
6. Sentiment: "positive" / "neutral" / "concerned"

Customer hint: {hint or 'not provided'}

Note text:
{text[:2000]}

Return ONLY valid JSON, no markdown wrapping:
{{"summary": "...", "customer_match": "..." or null, "action_items": [...], "dates_mentioned": [...], "products_mentioned": [...], "sentiment": "..."}}"""

        response = await llm_complete(prompt, system="You are a sales intelligence parser. Extract structured data from meeting notes. Respond in Chinese. Return ONLY valid JSON.")
        result = _safe_llm_json(response)
        if result and isinstance(result, dict):
            return {
                "summary": result.get("summary", text[:100]),
                "customer_match": result.get("customer_match") or hint,
                "action_items": result.get("action_items", []),
                "dates_mentioned": result.get("dates_mentioned", []),
                "products_mentioned": result.get("products_mentioned", []),
                "sentiment": result.get("sentiment", "neutral"),
            }
    except Exception as e:
        logger.warning("AI parse failed, using fallback: %s", e)

    return _parse_fallback(text, hint)


# ── Routes ──────────────────────────────────────────────────────────────────

@router.post("", status_code=status.HTTP_201_CREATED)
async def create_capture(
    body: QuickCaptureIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuickCaptureOut:
    """Submit a quick capture note (text or voice transcript)."""
    from src.models.quick_capture import QuickCapture

    cap = QuickCapture(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        source_type=body.source_type,
        raw_text=body.raw_text,
        customer_hint=body.customer_hint,
        opportunity_hint=body.opportunity_hint,
        status="raw",
    )
    db.add(cap)
    await db.commit()
    await db.refresh(cap)

    return QuickCaptureOut(
        id=str(cap.id),
        source_type=cap.source_type,
        raw_text=cap.raw_text,
        customer_hint=cap.customer_hint,
        opportunity_hint=cap.opportunity_hint,
        status=cap.status,
        parsed=None,
        followup_ids=None,
        created_at=cap.created_at.isoformat() if cap.created_at else "",
    )


@router.get("")
async def list_captures(
    limit: int = Query(20, ge=1, le=100),
    status: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[QuickCaptureOut]:
    """List quick captures for the tenant."""
    from src.models.quick_capture import QuickCapture

    q = select(QuickCapture).where(
        QuickCapture.tenant_id == current_user.tenant_id
    )
    if status:
        q = q.where(QuickCapture.status == status)
    q = q.order_by(QuickCapture.created_at.desc()).limit(limit)

    result = await db.execute(q)
    captures = result.scalars().all()

    return [
        QuickCaptureOut(
            id=str(c.id),
            source_type=c.source_type,
            raw_text=c.raw_text,
            customer_hint=c.customer_hint,
            opportunity_hint=c.opportunity_hint,
            status=c.status,
            parsed=c.parsed,
            followup_ids=c.followup_ids,
            created_at=c.created_at.isoformat() if c.created_at else "",
        )
        for c in captures
    ]


@router.get("/{capture_id}")
async def get_capture(
    capture_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuickCaptureOut:
    """Get a single quick capture by ID."""
    from src.models.quick_capture import QuickCapture

    result = await db.execute(
        select(QuickCapture).where(
            QuickCapture.id == capture_id,
            QuickCapture.tenant_id == current_user.tenant_id,
        )
    )
    cap = result.scalar_one_or_none()
    if cap is None:
        raise HTTPException(status_code=404, detail="Capture not found")

    return QuickCaptureOut(
        id=str(cap.id),
        source_type=cap.source_type,
        raw_text=cap.raw_text,
        customer_hint=cap.customer_hint,
        opportunity_hint=cap.opportunity_hint,
        status=cap.status,
        parsed=cap.parsed,
        followup_ids=cap.followup_ids,
        created_at=cap.created_at.isoformat() if cap.created_at else "",
    )


@router.post("/{capture_id}/process")
async def process_capture(
    capture_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """AI-parse a capture and create followup items from extracted action items.

    1. Parse raw text with LLM (or regex fallback)
    2. Find/map to existing opportunity if customer_hint matches
    3. Create FollowupItem for each action item
    4. Link followup IDs back to capture
    """
    from src.models.quick_capture import QuickCapture

    result = await db.execute(
        select(QuickCapture).where(
            QuickCapture.id == capture_id,
            QuickCapture.tenant_id == current_user.tenant_id,
        )
    )
    cap = result.scalar_one_or_none()
    if cap is None:
        raise HTTPException(status_code=404, detail="Capture not found")

    if cap.status == "processing":
        raise HTTPException(status_code=409, detail="Already processing")

    # Mark as processing
    cap.status = "processing"
    await db.commit()

    try:
        # AI parse
        parsed = await _ai_parse(cap.raw_text, cap.customer_hint)
        cap.parsed = parsed

        # Try to find matching opportunity
        opp_id = None
        customer = parsed.get("customer_match") or cap.customer_hint
        if customer:
            opp_result = await db.execute(
                select(Opportunity).where(
                    Opportunity.tenant_id == current_user.tenant_id,
                    Opportunity.name.ilike(f"%{customer}%"),
                ).limit(1)
            )
            opp = opp_result.scalar_one_or_none()
            if opp:
                opp_id = opp.id

        # If no matching opp, create one from the capture
        if opp_id is None:
            opp_name = customer or parsed.get("summary", "快速捕获商机")
            opp = Opportunity(
                tenant_id=current_user.tenant_id,
                name=opp_name,
                stage="lead_validation",
                notes=f"来源：快速捕获\n{capture_id}",
            )
            db.add(opp)
            await db.flush()
            opp_id = opp.id

        # Create followup items
        created_ids = []
        for item in parsed.get("action_items", []):
            fu = FollowupItem(
                opportunity_id=opp_id,
                tenant_id=current_user.tenant_id,
                title=item.get("title", "跟进项"),
                status=FollowupStatus.TODO,
                priority=item.get("priority", 1),
                review_level=ReviewLevel.COMMERCIAL,
                source_type="quick_capture",
                source_id=cap.id,
                created_by=current_user.id,
            )
            db.add(fu)
            await db.flush()
            created_ids.append(str(fu.id))

        cap.followup_ids = created_ids
        cap.status = "done"
        await db.commit()

        return {
            "status": "done",
            "capture_id": str(cap.id),
            "opportunity_id": str(opp_id),
            "parsed": parsed,
            "followup_ids": created_ids,
            "followup_count": len(created_ids),
        }

    except Exception as e:
        logger.exception("Process capture failed: %s", e)
        cap.status = "failed"
        cap.parsed = {"error": str(e)}
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")


@router.delete("/{capture_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_capture(
    capture_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a quick capture."""
    from src.models.quick_capture import QuickCapture

    result = await db.execute(
        select(QuickCapture).where(
            QuickCapture.id == capture_id,
            QuickCapture.tenant_id == current_user.tenant_id,
        )
    )
    cap = result.scalar_one_or_none()
    if cap is None:
        raise HTTPException(status_code=404, detail="Capture not found")

    await db.execute(delete(QuickCapture).where(QuickCapture.id == capture_id))
    await db.commit()
