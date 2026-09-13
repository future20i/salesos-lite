"""Kanban API routes — multi-column task board with agent-driven state machine.

Columns: triage → todo → ready → in_progress → pending_review → blocked → done
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import get_current_user
from src.database import get_db
from src.models.followup import (
    FollowupItem,
    FollowupStatus,
    FollowupEvent,
    FollowupRun,
    FollowupComment,
)
from src.models.user import User

router = APIRouter(prefix="/api/kanban", tags=["kanban"])

# ── Column order for the board ──────────────────────────────────────
COLUMNS = ["triage", "todo", "ready", "in_progress", "pending_review", "blocked", "done"]


# ── Pydantic schemas ────────────────────────────────────────────────

class KanbanTaskOut(BaseModel):
    id: str
    title: str
    body: str | None = None
    status: str
    priority: int = 0
    assignee_agent: str | None = None
    triage: bool = False
    result: str | None = None
    max_retries: int | None = None
    opportunity_id: str | None = None
    review_level: str | None = None
    assigned_to: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class KanbanRunOut(BaseModel):
    id: int
    followup_id: str
    agent_profile: str | None = None
    status: str | None = None
    outcome: str | None = None
    summary: str | None = None
    error: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    last_heartbeat_at: str | None = None


class KanbanCommentOut(BaseModel):
    id: int
    followup_id: str
    author: str | None = None
    body: str
    created_at: str | None = None


class KanbanEventOut(BaseModel):
    id: int
    kind: str
    payload: dict | None = None
    run_id: int | None = None
    created_at: str | None = None


class KanbanTaskDetailOut(BaseModel):
    task: KanbanTaskOut
    runs: list[KanbanRunOut] = []
    comments: list[KanbanCommentOut] = []
    events: list[KanbanEventOut] = []


class KanbanCreateIn(BaseModel):
    title: str
    body: str | None = None
    priority: int = 0
    assignee_agent: str | None = None
    triage: bool = False
    max_retries: int | None = None
    opportunity_id: str | None = None


class KanbanUpdateIn(BaseModel):
    title: str | None = None
    body: str | None = None
    priority: int | None = None
    assignee_agent: str | None = None
    triage: bool | None = None
    max_retries: int | None = None


class KanbanClaimIn(BaseModel):
    agent_profile: str | None = None


class KanbanCompleteIn(BaseModel):
    result: str | None = None
    summary: str | None = None


class KanbanBlockIn(BaseModel):
    reason: str | None = None


class KanbanCommentIn(BaseModel):
    author: str | None = None
    body: str


# ── Helpers ─────────────────────────────────────────────────────────

def _fmt_ts(dt) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def _task_out(t: FollowupItem) -> KanbanTaskOut:
    return KanbanTaskOut(
        id=str(t.id),
        title=t.title,
        body=t.body,
        status=t.status.value if hasattr(t.status, "value") else t.status,
        priority=t.priority,
        assignee_agent=t.assignee_agent,
        triage=t.triage,
        result=t.result,
        max_retries=t.max_retries,
        opportunity_id=str(t.opportunity_id) if t.opportunity_id else None,
        review_level=t.review_level.value if t.review_level else None,
        assigned_to=str(t.assigned_to) if t.assigned_to else None,
        created_at=_fmt_ts(t.created_at),
        started_at=_fmt_ts(t.started_at),
        completed_at=_fmt_ts(t.completed_at),
    )


async def _add_event(
    db: AsyncSession,
    followup_id: uuid.UUID,
    kind: str,
    payload: dict | None = None,
    run_id: int | None = None,
) -> FollowupEvent:
    ev = FollowupEvent(
        followup_id=followup_id,
        kind=kind,
        payload=payload,
        run_id=run_id,
    )
    db.add(ev)
    await db.flush()
    return ev


# ── Routes ──────────────────────────────────────────────────────────

@router.get("/tasks", response_model=list[KanbanTaskOut])
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    assignee: Optional[str] = Query(None, description="Filter by assignee agent profile"),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all followup tasks for the kanban board, optionally filtered."""
    q = select(FollowupItem).where(FollowupItem.tenant_id == user.tenant_id)
    if status:
        q = q.where(FollowupItem.status == status)
    if assignee:
        q = q.where(FollowupItem.assignee_agent == assignee)
    if not include_archived:
        # Exclude archived tasks (those with status=done from long ago? for now just show all)
        pass  # TODO: add archived flag column later

    q = q.order_by(
        FollowupItem.priority.desc(),
        FollowupItem.created_at.asc(),
    )
    result = await db.execute(q)
    tasks = result.scalars().all()
    return [_task_out(t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=KanbanTaskDetailOut)
async def get_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Get full task detail with runs, comments, and events."""
    q = select(FollowupItem).where(
        FollowupItem.id == task_id,
        FollowupItem.tenant_id == user.tenant_id,
    )
    result = await db.execute(q)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    # Fetch runs
    runs_q = select(FollowupRun).where(FollowupRun.followup_id == task_id).order_by(FollowupRun.id.desc())
    runs_result = await db.execute(runs_q)
    runs = runs_result.scalars().all()

    # Fetch comments
    comments_q = select(FollowupComment).where(FollowupComment.followup_id == task_id).order_by(FollowupComment.created_at)
    comments_result = await db.execute(comments_q)
    comments = comments_result.scalars().all()

    # Fetch events
    events_q = select(FollowupEvent).where(FollowupEvent.followup_id == task_id).order_by(FollowupEvent.created_at.desc()).limit(50)
    events_result = await db.execute(events_q)
    events = events_result.scalars().all()

    return KanbanTaskDetailOut(
        task=_task_out(task),
        runs=[
            KanbanRunOut(
                id=r.id,
                followup_id=str(r.followup_id),
                agent_profile=r.agent_profile,
                status=r.status,
                outcome=r.outcome,
                summary=r.summary,
                error=r.error,
                started_at=_fmt_ts(r.started_at),
                ended_at=_fmt_ts(r.ended_at),
                last_heartbeat_at=_fmt_ts(r.last_heartbeat_at),
            )
            for r in runs
        ],
        comments=[
            KanbanCommentOut(
                id=c.id,
                followup_id=str(c.followup_id),
                author=c.author,
                body=c.body,
                created_at=_fmt_ts(c.created_at),
            )
            for c in comments
        ],
        events=[
            KanbanEventOut(
                id=e.id,
                kind=e.kind,
                payload=e.payload,
                run_id=e.run_id,
                created_at=_fmt_ts(e.created_at),
            )
            for e in events
        ],
    )


@router.post("/tasks", response_model=KanbanTaskOut, status_code=201)
async def create_task(
    body: KanbanCreateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new kanban task."""
    opp_id = uuid.UUID(body.opportunity_id) if body.opportunity_id else None
    initial_status = FollowupStatus.TRIAGE if body.triage else FollowupStatus.TODO

    task = FollowupItem(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        opportunity_id=opp_id,
        title=body.title,
        body=body.body,
        status=initial_status,
        priority=body.priority,
        assignee_agent=body.assignee_agent,
        triage=body.triage,
        max_retries=body.max_retries,
        created_by=user.id,
        source_type="kanban",
    )
    db.add(task)
    try:
        await db.flush()
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, f"DB error: {e}")
    await _add_event(db, task.id, "created", {"title": body.title, "triage": body.triage})
    await db.commit()
    return _task_out(task)


@router.patch("/tasks/{task_id}", response_model=KanbanTaskOut)
async def update_task(
    task_id: uuid.UUID,
    body: KanbanUpdateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update task fields (title, body, priority, assignee, etc.)."""
    q = select(FollowupItem).where(
        FollowupItem.id == task_id,
        FollowupItem.tenant_id == user.tenant_id,
    )
    result = await db.execute(q)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    if body.title is not None:
        task.title = body.title
    if body.body is not None:
        task.body = body.body
    if body.priority is not None:
        task.priority = body.priority
    if body.assignee_agent is not None:
        task.assignee_agent = body.assignee_agent
    if body.triage is not None:
        task.triage = body.triage
    if body.max_retries is not None:
        task.max_retries = body.max_retries

    await db.commit()
    return _task_out(task)


# ── Status transitions ──────────────────────────────────────────────

@router.post("/tasks/{task_id}/specify")
async def specify_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Move task from triage → todo (after AI spec expansion)."""
    q = select(FollowupItem).where(
        FollowupItem.id == task_id,
        FollowupItem.tenant_id == user.tenant_id,
    )
    result = await db.execute(q)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status != FollowupStatus.TRIAGE:
        raise HTTPException(400, "Only triage tasks can be specified")

    task.status = FollowupStatus.TODO
    task.triage = False
    await _add_event(db, task.id, "specified")
    await db.commit()
    return {"ok": True, "status": task.status.value}


@router.post("/tasks/{task_id}/ready")
async def ready_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Promote task from todo → ready (eligible for agent dispatch)."""
    q = select(FollowupItem).where(
        FollowupItem.id == task_id,
        FollowupItem.tenant_id == user.tenant_id,
    )
    result = await db.execute(q)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status != FollowupStatus.TODO:
        raise HTTPException(400, "Only todo tasks can be promoted to ready")

    task.status = FollowupStatus.READY
    await _add_event(db, task.id, "dispatched")
    await db.commit()
    return {"ok": True, "status": task.status.value}


@router.post("/tasks/{task_id}/claim")
async def claim_task(
    task_id: uuid.UUID,
    body: KanbanClaimIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Claim a todo/ready task and start a run (agent begins work)."""
    q = select(FollowupItem).where(
        FollowupItem.id == task_id,
        FollowupItem.tenant_id == user.tenant_id,
    )
    result = await db.execute(q)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status not in (FollowupStatus.TODO, FollowupStatus.READY):
        raise HTTPException(400, f"Cannot claim task with status {task.status}")

    task.status = FollowupStatus.IN_PROGRESS
    task.started_at = datetime.now(timezone.utc)

    # Create a run record
    run = FollowupRun(
        followup_id=task.id,
        agent_profile=body.agent_profile or task.assignee_agent,
        status="running",
        started_at=datetime.now(timezone.utc),
        last_heartbeat_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.flush()
    await _add_event(db, task.id, "claimed", {"agent": body.agent_profile}, run_id=run.id)
    await db.commit()
    return {"ok": True, "status": task.status.value, "run_id": run.id}


@router.post("/tasks/{task_id}/complete")
async def complete_task(
    task_id: uuid.UUID,
    body: KanbanCompleteIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Mark task as done with optional result text."""
    q = select(FollowupItem).where(
        FollowupItem.id == task_id,
        FollowupItem.tenant_id == user.tenant_id,
    )
    result = await db.execute(q)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    task.status = FollowupStatus.DONE
    task.completed_at = datetime.now(timezone.utc)
    if body.result:
        task.result = body.result

    # Update latest run
    run_q = select(FollowupRun).where(
        FollowupRun.followup_id == task.id,
        FollowupRun.status == "running",
    ).order_by(FollowupRun.id.desc()).limit(1)
    run_result = await db.execute(run_q)
    run = run_result.scalar_one_or_none()
    run_id = None
    if run:
        run.status = "completed"
        run.outcome = "success"
        if body.summary:
            run.summary = body.summary
        run.ended_at = datetime.now(timezone.utc)
        run_id = run.id

    await _add_event(db, task.id, "completed", {"result": body.result}, run_id=run_id)
    await db.commit()
    return {"ok": True, "status": task.status.value}


@router.post("/tasks/{task_id}/block")
async def block_task(
    task_id: uuid.UUID,
    body: KanbanBlockIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Block a task (todo/ready/in_progress → blocked)."""
    q = select(FollowupItem).where(
        FollowupItem.id == task_id,
        FollowupItem.tenant_id == user.tenant_id,
    )
    result = await db.execute(q)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status not in (FollowupStatus.TODO, FollowupStatus.READY, FollowupStatus.IN_PROGRESS):
        raise HTTPException(400, f"Cannot block task with status {task.status}")

    task.status = FollowupStatus.BLOCKED
    await _add_event(db, task.id, "blocked", {"reason": body.reason})
    await db.commit()
    return {"ok": True, "status": task.status.value}


@router.post("/tasks/{task_id}/unblock")
async def unblock_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Unblock a task → ready."""
    q = select(FollowupItem).where(
        FollowupItem.id == task_id,
        FollowupItem.tenant_id == user.tenant_id,
    )
    result = await db.execute(q)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status != FollowupStatus.BLOCKED:
        raise HTTPException(400, f"Cannot unblock task with status {task.status}")

    task.status = FollowupStatus.READY
    await _add_event(db, task.id, "unblocked")
    await db.commit()
    return {"ok": True, "status": task.status.value}


@router.post("/tasks/{task_id}/reclaim")
async def reclaim_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reclaim a running task → ready (stale worker detection)."""
    q = select(FollowupItem).where(
        FollowupItem.id == task_id,
        FollowupItem.tenant_id == user.tenant_id,
    )
    result = await db.execute(q)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status != FollowupStatus.IN_PROGRESS:
        raise HTTPException(400, f"Cannot reclaim task with status {task.status}")

    task.status = FollowupStatus.READY

    # Mark current run as reclaimed
    run_q = select(FollowupRun).where(
        FollowupRun.followup_id == task.id,
        FollowupRun.status == "running",
    ).order_by(FollowupRun.id.desc()).limit(1)
    run_result = await db.execute(run_q)
    run = run_result.scalar_one_or_none()
    run_id = None
    if run:
        run.status = "reclaimed"
        run.outcome = "reclaimed"
        run.ended_at = datetime.now(timezone.utc)
        run_id = run.id

    await _add_event(db, task.id, "reclaimed", {"reason": "reclaimed from kanban"}, run_id=run_id)
    await db.commit()
    return {"ok": True, "status": task.status.value}


@router.post("/tasks/{task_id}/archive")
async def archive_task(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Archive a task (soft-delete, sets status to done if not already)."""
    q = select(FollowupItem).where(
        FollowupItem.id == task_id,
        FollowupItem.tenant_id == user.tenant_id,
    )
    result = await db.execute(q)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    # Mark as done if not already
    if task.status != FollowupStatus.DONE:
        task.status = FollowupStatus.DONE
        task.completed_at = datetime.now(timezone.utc)

    await _add_event(db, task.id, "archived")
    await db.commit()
    return {"ok": True}


# ── Comments ────────────────────────────────────────────────────────

@router.post("/tasks/{task_id}/comment", response_model=KanbanCommentOut, status_code=201)
async def add_comment(
    task_id: uuid.UUID,
    body: KanbanCommentIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add a comment to a task."""
    # Verify task exists
    q = select(FollowupItem).where(
        FollowupItem.id == task_id,
        FollowupItem.tenant_id == user.tenant_id,
    )
    result = await db.execute(q)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    comment = FollowupComment(
        followup_id=task_id,
        author=body.author or user.name or "user",
        body=body.body,
    )
    db.add(comment)
    await _add_event(db, task_id, "comment", {"author": comment.author})
    await db.commit()
    return KanbanCommentOut(
        id=comment.id,
        followup_id=str(comment.followup_id),
        author=comment.author,
        body=comment.body,
        created_at=_fmt_ts(comment.created_at),
    )


# ── Heartbeat ───────────────────────────────────────────────────────

@router.post("/tasks/{task_id}/heartbeat")
async def heartbeat(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update heartbeat timestamp on the current run (agent signals it's still alive)."""
    q = select(FollowupItem).where(
        FollowupItem.id == task_id,
        FollowupItem.tenant_id == user.tenant_id,
    )
    result = await db.execute(q)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(404, "Task not found")

    run_q = select(FollowupRun).where(
        FollowupRun.followup_id == task_id,
        FollowupRun.status == "running",
    ).order_by(FollowupRun.id.desc()).limit(1)
    run_result = await db.execute(run_q)
    run = run_result.scalar_one_or_none()

    if run:
        run.last_heartbeat_at = datetime.now(timezone.utc)

    await _add_event(db, task_id, "heartbeat")
    await db.commit()
    return {"ok": True}


# ── Board summary ───────────────────────────────────────────────────

@router.get("/board")
async def board_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return column counts for the kanban board."""
    q = (
        select(FollowupItem.status, func.count(FollowupItem.id))
        .where(FollowupItem.tenant_id == user.tenant_id)
        .group_by(FollowupItem.status)
    )
    result = await db.execute(q)
    counts = {row[0].value if hasattr(row[0], "value") else row[0]: row[1] for row in result}

    # Ensure all columns appear, even if zero
    board = {col: counts.get(col, 0) for col in COLUMNS}
    board["total"] = sum(board.values())
    return board
