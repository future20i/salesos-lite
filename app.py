"""SalesOS Lite — single-file FastAPI entry point."""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import engine, get_db
from models import Base
from auth import seed_users, get_current_user, verify_password, create_token
from inbox import router as inbox_router
from approval import router as approval_router

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed_users(db)
    yield
    engine.dispose()


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

# Static SPA
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
