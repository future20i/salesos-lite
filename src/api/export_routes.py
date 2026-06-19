"""Data export routes — CSV export for leads and messages."""

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database import get_db
from src.models.lead import Lead, LeadStatus
from src.models.message import Message, MessageDirection
from src.auth import get_current_user
from src.models.user import User, UserRole

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/leads")
async def export_leads_csv(
    status: str | None = Query(None, description="Filter by lead status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export all leads with their messages as CSV."""
    
    query = select(Lead).where(Lead.tenant_id == current_user.tenant_id)
    
    if status:
        try:
            query = query.where(Lead.status == LeadStatus(status))
        except ValueError:
            pass
    
    query = query.order_by(Lead.last_activity_at.desc().nulls_last())
    result = await db.execute(query)
    leads = result.scalars().all()
    
    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "线索ID", "客户名称", "渠道", "状态", "意向",
        "消息方向", "发送者", "消息内容", "消息时间",
        "线索创建时间", "最后活动时间"
    ])
    
    for lead in leads:
        # Fetch messages for this lead
        msg_result = await db.execute(
            select(Message)
            .where(Message.lead_id == lead.id, Message.tenant_id == current_user.tenant_id)
            .order_by(Message.created_at.asc())
        )
        messages = msg_result.scalars().all()
        
        if not messages:
            # Export lead without messages
            writer.writerow([
                str(lead.id), lead.customer_name, lead.channel.value if lead.channel else "",
                lead.status.value if lead.status else "", lead.intent.value if lead.intent else "",
                "", "", "", "",
                lead.created_at.isoformat() if lead.created_at else "",
                lead.last_activity_at.isoformat() if lead.last_activity_at else "",
            ])
        else:
            for msg in messages:
                writer.writerow([
                    str(lead.id), lead.customer_name, lead.channel.value if lead.channel else "",
                    lead.status.value if lead.status else "", lead.intent.value if lead.intent else "",
                    msg.direction.value if msg.direction else "",
                    msg.sender or "",
                    msg.content or "",
                    msg.created_at.isoformat() if msg.created_at else "",
                    lead.created_at.isoformat() if lead.created_at else "",
                    lead.last_activity_at.isoformat() if lead.last_activity_at else "",
                ])
    
    output.seek(0)
    
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"salesos-leads-{timestamp}.csv"
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
