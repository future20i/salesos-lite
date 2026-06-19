"""Phase 4 — Inbox API integration tests."""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from tests.app_for_test import app
from src.database import get_db
from src.models.tenant import Tenant
from src.models.user import User, UserRole
from src.auth import hash_password, create_token


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


@pytest_asyncio.fixture(scope="function")
async def seeded_client(client, db_session):
    """Seed a tenant + admin user, return client + token + tenant_id."""
    # Create tenant
    tenant = Tenant(name="InboxTestCo")
    db_session.add(tenant)
    await db_session.flush()

    # Create admin user
    user = User(
        tenant_id=tenant.id,
        username="inboxadmin",
        email="admin@inboxtest.com",
        password_hash=hash_password("testpass123"),
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()

    token = create_token(str(user.id), str(user.tenant_id), user.role.value)
    return client, token, str(tenant.id), user


# ── Tests ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_incoming_public(seeded_client):
    """POST /api/inbox/incoming — no auth required, creates lead + message."""
    client, token, tenant_id, _ = seeded_client

    resp = await client.post(
        "/api/inbox/incoming",
        json={
            "customer_name": "Alice",
            "content": "I'd like to buy 100 units of product X",
            "channel": "web",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "lead_id" in data
    assert "message_id" in data
    assert data["lead_id"] is not None


@pytest.mark.asyncio
async def test_incoming_existing_lead(seeded_client, db_session):
    """Second message from same customer reuses the lead."""
    client, token, tenant_id, _ = seeded_client

    # First message
    resp1 = await client.post(
        "/api/inbox/incoming",
        json={
            "customer_name": "Bob",
            "content": "First message",
            "channel": "web",
        },
    )
    assert resp1.status_code == 201
    lead_id_1 = resp1.json()["lead_id"]

    # Second message from same customer
    resp2 = await client.post(
        "/api/inbox/incoming",
        json={
            "customer_name": "Bob",
            "content": "Second message",
            "channel": "web",
        },
    )
    assert resp2.status_code == 201
    lead_id_2 = resp2.json()["lead_id"]

    # Same lead should be reused
    assert lead_id_1 == lead_id_2


@pytest.mark.asyncio
async def test_incoming_with_channel_message_id(seeded_client):
    """incoming with optional channel_message_id."""
    client, token, tenant_id, _ = seeded_client

    resp = await client.post(
        "/api/inbox/incoming",
        json={
            "customer_name": "Carol",
            "content": "Hello via WhatsApp",
            "channel": "whatsapp",
            "channel_message_id": "wa_12345",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "lead_id" in data
    assert "message_id" in data


@pytest.mark.asyncio
async def test_list_leads_authenticated(seeded_client, db_session):
    """GET /api/inbox/leads — returns leads for tenant."""
    client, token, tenant_id, _ = seeded_client

    # Create a lead first via incoming
    await client.post(
        "/api/inbox/incoming",
        json={
            "customer_name": "Dave",
            "content": "I need a quote",
            "channel": "web",
        },
    )

    # List leads
    resp = await client.get(
        "/api/inbox/leads",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    # Check structure
    lead = data[0]
    assert "id" in lead
    assert "customer_name" in lead
    assert "channel" in lead
    assert "status" in lead
    assert "unread" in lead
    assert "last_activity_at" in lead


@pytest.mark.asyncio
async def test_list_leads_unauthorized(seeded_client):
    """GET /api/inbox/leads without token returns 401."""
    client, token, tenant_id, _ = seeded_client

    resp = await client.get("/api/inbox/leads")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_lead_detail(seeded_client):
    """GET /api/inbox/leads/{id} returns lead with messages."""
    client, token, tenant_id, _ = seeded_client

    # Create lead
    resp = await client.post(
        "/api/inbox/incoming",
        json={
            "customer_name": "Eve",
            "content": "Hello, I have a question",
            "channel": "web",
        },
    )
    lead_id = resp.json()["lead_id"]

    # Get detail
    resp = await client.get(
        f"/api/inbox/leads/{lead_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == lead_id
    assert data["customer_name"] == "Eve"
    assert data["unread"] is False  # Marked as read
    assert len(data["messages"]) >= 1
    assert data["messages"][0]["content"] == "Hello, I have a question"
    assert data["messages"][0]["direction"] == "inbound"


@pytest.mark.asyncio
async def test_get_lead_not_found(seeded_client):
    """GET /api/inbox/leads/{id} with non-existent lead returns 404."""
    client, token, tenant_id, _ = seeded_client

    resp = await client.get(
        "/api/inbox/leads/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reply_to_lead(seeded_client):
    """POST /api/inbox/leads/{id}/reply creates outbound message."""
    client, token, tenant_id, _ = seeded_client

    # Create lead
    resp = await client.post(
        "/api/inbox/incoming",
        json={
            "customer_name": "Frank",
            "content": "I'm interested",
            "channel": "web",
        },
    )
    lead_id = resp.json()["lead_id"]

    # Reply
    resp = await client.post(
        f"/api/inbox/leads/{lead_id}/reply",
        json={"content": "Thanks for your interest! Here's our catalog."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "message_id" in data

    # Verify message in lead detail
    resp = await client.get(
        f"/api/inbox/leads/{lead_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    messages = resp.json()["messages"]
    outbound_messages = [m for m in messages if m["direction"] == "outbound"]
    assert len(outbound_messages) >= 1
    assert outbound_messages[-1]["content"] == "Thanks for your interest! Here's our catalog."


@pytest.mark.asyncio
async def test_assign_lead(seeded_client, db_session):
    """POST /api/inbox/leads/{id}/assign — manager assigns lead."""
    client, token, tenant_id, _ = seeded_client

    # Create a rep user in the same tenant
    rep = User(
        tenant_id=uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id,
        username="rep1",
        email="rep1@test.com",
        password_hash=hash_password("pass123"),
        role=UserRole.REP,
    )
    db_session.add(rep)
    await db_session.commit()
    await db_session.refresh(rep)

    # Create lead
    resp = await client.post(
        "/api/inbox/incoming",
        json={
            "customer_name": "Grace",
            "content": "I need help",
            "channel": "web",
        },
    )
    lead_id = resp.json()["lead_id"]

    # Assign lead
    resp = await client.post(
        f"/api/inbox/leads/{lead_id}/assign",
        json={"user_id": str(rep.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "assigned"


@pytest.mark.asyncio
async def test_assign_lead_forbidden_for_rep(seeded_client, db_session):
    """Rep cannot assign leads."""
    client, token, tenant_id, _ = seeded_client

    # Create a rep user
    rep = User(
        tenant_id=uuid.UUID(tenant_id),
        username="rep2",
        email="rep2@test.com",
        password_hash=hash_password("pass123"),
        role=UserRole.REP,
    )
    db_session.add(rep)
    await db_session.commit()
    await db_session.refresh(rep)

    rep_token = create_token(str(rep.id), str(rep.tenant_id), rep.role.value)

    # Create lead
    resp = await client.post(
        "/api/inbox/incoming",
        json={
            "customer_name": "Heidi",
            "content": "Help please",
            "channel": "web",
        },
    )
    lead_id = resp.json()["lead_id"]

    # Try assign as rep
    resp = await client.post(
        f"/api/inbox/leads/{lead_id}/assign",
        json={"user_id": str(rep.id)},
        headers={"Authorization": f"Bearer {rep_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_rep_sees_only_assigned_leads(seeded_client, db_session):
    """Rep listing only shows assigned leads."""
    client, token, tenant_id, _ = seeded_client

    # Create leads via incoming (they'll be unassigned)
    await client.post(
        "/api/inbox/incoming",
        json={"customer_name": "Unassigned1", "content": "hi", "channel": "web"},
    )
    await client.post(
        "/api/inbox/incoming",
        json={"customer_name": "Unassigned2", "content": "hello", "channel": "web"},
    )

    # Create rep
    rep = User(
        tenant_id=uuid.UUID(tenant_id),
        username="rep3",
        email="rep3@test.com",
        password_hash=hash_password("pass123"),
        role=UserRole.REP,
    )
    db_session.add(rep)
    await db_session.commit()
    await db_session.refresh(rep)

    rep_token = create_token(str(rep.id), str(rep.tenant_id), rep.role.value)

    # Rep sees no leads (none assigned)
    resp = await client.get(
        "/api/inbox/leads",
        headers={"Authorization": f"Bearer {rep_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 0  # No leads assigned to rep

    # Admin sees all leads
    resp = await client.get(
        "/api/inbox/leads",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2  # Admins see all
