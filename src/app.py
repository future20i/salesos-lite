"""
Phase 7 — Main FastAPI application (M1 app assembly).

Creates the FastAPI app, wires up:
- Lifespan: create tables, enable RLS, start background AI pipeline tasks
- CORS middleware (allow all origins for dev)
- tenant_context_middleware
- All routers: auth, inbox, channels
- GET /api/health → health_endpoint
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from src.database import engine, AsyncSessionLocal
from src.models.base import Base
from src.rls import enable_rls_for_all
from src.middleware import tenant_context_middleware
from src.api.auth_routes import router as auth_router
from src.api.inbox_routes import router as inbox_router
from src.api.channel_routes import router as channel_router
from src.api.export_routes import router as export_router
from src.api.billing_routes import router as billing_router
from src.api.onboarding_routes import router as onboarding_router
from src.api.dashboard_routes import router as dashboard_router
from src.api.canned_routes import router as canned_router
from src.api.whatsapp_routes import router as whatsapp_router
from src.api.suggest_routes import router as suggest_router
from src.api.approval_routes import router as approval_router
from src.api.email_routes import router as email_router
from src.api.notification_routes import router as notification_router
from src.api.followup_routes import router as followup_rule_router, items_router as followup_item_router, followup_evaluation_loop, seed_default_rules
from src.api.quotation_routes import router as quotation_router
from src.api.opportunity_routes import router as opportunity_router
from src.api.knowledge_routes import router as knowledge_router
from src.health import health_endpoint
from src.ai_pipeline import poll_and_process, recover_stale_jobs

logger = logging.getLogger(__name__)

# ── Background task control ──────────────────────────────────────────────
_ai_pipeline_task: asyncio.Task | None = None
_followup_task: asyncio.Task | None = None
_silence_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create tables, enable RLS, start background AI pipeline tasks."""
    # ── Startup ──────────────────────────────────────────────────────────
    logger.info("Creating database tables and enabling RLS…")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await enable_rls_for_all(conn)

    # Run a one-shot stale-job recovery on startup
    try:
        async with AsyncSessionLocal() as session:
            recovered = await recover_stale_jobs()
            if recovered:
                logger.info("Recovered %d stale AI jobs on startup", recovered)
    except Exception:
        logger.exception("Startup stale-job recovery failed")

    # Start the AI pipeline as a background task
    global _ai_pipeline_task
    _ai_pipeline_task = asyncio.create_task(_run_ai_pipeline())
    logger.info("AI pipeline background task started")

    # Seed default followup rules + start evaluation loop
    try:
        async with AsyncSessionLocal() as session:
            await seed_default_rules(session)
    except Exception:
        logger.exception("Seed default rules failed")

    global _followup_task
    _followup_task = asyncio.create_task(followup_evaluation_loop(interval_seconds=60))
    logger.info("Followup evaluation loop started")

    # Start silence check loop
    from src.pipeline import silence_check_loop
    global _silence_task
    _silence_task = asyncio.create_task(silence_check_loop(interval_seconds=3600))
    logger.info("Silence check loop started")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────
    if _ai_pipeline_task is not None:
        _ai_pipeline_task.cancel()
        try:
            await _ai_pipeline_task
        except asyncio.CancelledError:
            pass
        logger.info("AI pipeline background task cancelled")

    if _followup_task is not None:
        _followup_task.cancel()
        try:
            await _followup_task
        except asyncio.CancelledError:
            pass
        logger.info("Followup evaluation loop cancelled")

    if _silence_task is not None:
        _silence_task.cancel()
        try:
            await _silence_task
        except asyncio.CancelledError:
            pass
        logger.info("Silence check loop cancelled")

    await engine.dispose()
    logger.info("Database engine disposed")


async def _run_ai_pipeline():
    """Run the AI polling loop forever (with graceful cancellation)."""
    try:
        await poll_and_process(interval_seconds=2.0, max_iterations=None)
    except asyncio.CancelledError:
        logger.info("AI pipeline cancelled")
        raise
    except Exception:
        logger.exception("AI pipeline exited unexpectedly")


# ── App creation ─────────────────────────────────────────────────────────

app = FastAPI(
    title="SalesOS Lite",
    version="0.1.0",
    lifespan=lifespan,
)

# ── Middleware ───────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(tenant_context_middleware)

# ── Routes ──────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(inbox_router)
app.include_router(channel_router)
app.include_router(export_router)
app.include_router(billing_router)
app.include_router(onboarding_router)
app.include_router(dashboard_router)
app.include_router(canned_router)
app.include_router(whatsapp_router)
app.include_router(suggest_router)
app.include_router(approval_router)
app.include_router(email_router)
app.include_router(notification_router)
app.include_router(followup_rule_router)
app.include_router(followup_item_router)
app.include_router(quotation_router)
app.include_router(opportunity_router)
app.include_router(knowledge_router)

# Static SPA — serve index.html at root
_static_index = (Path(__file__).parent.parent / "static" / "index.html").read_text(encoding="utf-8")
_static_widget = (Path(__file__).parent.parent / "static" / "widget.js").read_text(encoding="utf-8")

from fastapi.responses import HTMLResponse, Response

@app.get("/", response_class=HTMLResponse)
async def root():
    return _static_index

@app.get("/widget.js")
async def widget():
    return Response(content=_static_widget, media_type="application/javascript")


@app.get("/api/health")
async def health():
    return await health_endpoint()
