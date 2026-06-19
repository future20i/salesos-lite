"""Minimal FastAPI app for testing.

Mounts the auth, inbox, and channel routers.
"""
from fastapi import FastAPI
from src.api.auth_routes import router as auth_router
from src.api.inbox_routes import router as inbox_router
from src.api.channel_routes import router as channel_router

app = FastAPI()
app.include_router(auth_router)
app.include_router(inbox_router)
app.include_router(channel_router)
