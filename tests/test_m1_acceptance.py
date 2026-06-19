"""
Phase 7 — M1 acceptance smoke test (Phase 7 deliverable).

Covers the full happy path end-to-end:
1. Register a company → get token
2. Post incoming message → verify lead created
3. GET leads with auth → verify customer name visible
4. GET /api/health → 200
5. Verify all business tables have RLS enabled
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.database import get_db
from src.rls import verify_rls
# Use the main src.app (not tests/app_for_test)
from src.app import app


@pytest.fixture(scope="function")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    """Override the get_db dependency with the test db_session."""

    async def _override():
        yield db_session

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_m1_smoke_register_incoming_leads(client, db_session):
    """Full M1 happy path: register → incoming → list leads."""

    # 1. Register a company → get token
    resp = await client.post(
        "/api/auth/register",
        json={
            "company_name": "SmokeTestCo",
            "username": "smoke_admin",
            "email": "smoke_admin@smoketest.com",
            "password": "supersecure123",
        },
    )
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    data = resp.json()
    assert "token" in data
    token = data["token"]
    tenant_id = data["user"]["tenant_id"]
    assert data["user"]["username"] == "smoke_admin"
    assert data["user"]["role"] == "admin"

    # 2. Post incoming message → verify lead created
    resp = await client.post(
        "/api/inbox/incoming",
        json={
            "customer_name": "Alice Customer",
            "content": "I would like to place an order for 50 units please.",
            "channel": "web",
        },
    )
    assert resp.status_code == 201, f"Incoming failed: {resp.text}"
    incoming_data = resp.json()
    assert "lead_id" in incoming_data
    assert "message_id" in incoming_data
    lead_id = incoming_data["lead_id"]

    # 3. GET leads with auth → verify customer name visible
    resp = await client.get(
        "/api/inbox/leads",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, f"List leads failed: {resp.text}"
    leads = resp.json()
    assert len(leads) >= 1

    # Find our lead
    lead_ids = [l["id"] for l in leads]
    assert lead_id in lead_ids, f"Lead {lead_id} not found in {lead_ids}"

    # Verify customer_name is visible
    lead = next(l for l in leads if l["id"] == lead_id)
    assert lead["customer_name"] == "Alice Customer"
    assert lead["channel"] == "web"
    assert lead["status"] == "new"
    assert lead["unread"] is True
    assert "last_activity_at" in lead


@pytest.mark.asyncio
async def test_m1_smoke_health(client):
    """GET /api/health returns 200."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200, f"Health check failed: {resp.text}"
    data = resp.json()
    assert data["status"] == "healthy"
    # pool info may or may not be present in test env
    if "pool_used" in data:
        assert isinstance(data["pool_used"], int)
    if "pool_total" in data:
        assert isinstance(data["pool_total"], int)


@pytest.mark.asyncio
async def test_m1_smoke_rls_enabled(db_session):
    """All business tables must have RLS enabled."""
    from src.rls import enable_rls_for_all

    await enable_rls_for_all(db_session)
    missing = await verify_rls(db_session)
    assert missing == [], f"Missing RLS on tables: {missing}"
