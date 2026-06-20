"""SalesOS Lite — single-file FastAPI entry point."""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import AsyncSessionLocal, engine, get_db
from models import Base
from auth import seed_users, get_current_user, verify_password, create_token
from inbox import router as inbox_router
from approval import router as approval_router
from src.api.notification_routes import router as notification_router
from src.api.followup_routes import router as followup_router
from src.api.followup_routes import seed_default_rules, evaluate_rules_for_tenant

logger = logging.getLogger(__name__)
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# ── Background evaluation loop ─────────────────────────────────────

FOLLOWUP_INTERVAL_SECONDS = 60


async def followup_evaluation_loop():
    """Background task: evaluate follow-up rules for all tenants every 60s."""
    while True:
        try:
            from src.models.tenant import Tenant
            from sqlalchemy import select

            async with AsyncSessionLocal() as db:
                tenant_result = await db.execute(select(Tenant))
                tenants = tenant_result.scalars().all()
                total_logs = 0
                for tenant in tenants:
                    logs = await evaluate_rules_for_tenant(db, tenant.id)
                    total_logs += len(logs)

                if total_logs:
                    logger.info(
                        "Followup engine: %d action(s) executed across %d tenant(s)",
                        total_logs,
                        len(tenants),
                    )
        except Exception:
            logger.exception("Followup evaluation loop error")

        await asyncio.sleep(FOLLOWUP_INTERVAL_SECONDS)


# ── Lifespan ───────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables (sync, since create_all is sync)
    Base.metadata.create_all(engine)

    # Seed data
    with Session(engine) as db:
        seed_users(db)

    async with AsyncSessionLocal() as db:
        await seed_default_rules(db)

    # Start background evaluation loop
    task = asyncio.create_task(followup_evaluation_loop())
    logger.info("Followup evaluation loop started (interval=%ds)", FOLLOWUP_INTERVAL_SECONDS)

    yield

    # Cleanup
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    engine.dispose()


# ── App ────────────────────────────────────────────────────────────

app = FastAPI(title="SalesOS Lite", version="0.1.0", lifespan=lifespan)


# Auth endpoints
class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    from models import User
    from sqlalchemy import select
    user = db.execute(select(User).where(User.username == body.username)).scalar()
    if not user or not verify_password(body.password, user.password_hash):
        return {"error": "Invalid credentials"}, 401
    token = create_token(user.id, user.username, user.role.value)
    return {
        "token": token,
        "user": {"id": user.id, "username": user.username, "role": user.role.value},
    }


@app.get("/api/auth/me")
def me(user=Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "role": user.role.value}


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Routers
app.include_router(inbox_router)
app.include_router(approval_router)
app.include_router(notification_router)
app.include_router(followup_router)

# Static SPA
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
