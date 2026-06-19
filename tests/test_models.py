import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_all_tables_created(db_session):
    """Verify all expected tables exist."""
    result = await db_session.execute(text(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
    ))
    tables = [row[0] for row in result]
    expected = ["ai_jobs", "approvals", "canned_responses",
                "leads", "messages", "tenants", "users"]
    for t in expected:
        assert t in tables, f"Table {t} not found"


@pytest.mark.asyncio
async def test_tenant_creation(db_session):
    from src.models import Tenant
    tenant = Tenant(name="Test Corp")
    db_session.add(tenant)
    await db_session.commit()
    assert tenant.id is not None
    assert tenant.name == "Test Corp"


@pytest.mark.asyncio
async def test_user_creation(db_session):
    from src.models import Tenant, User, UserRole
    tenant = Tenant(name="Test Corp")
    db_session.add(tenant)
    await db_session.flush()

    user = User(
        tenant_id=tenant.id,
        username="admin",
        email="admin@test.com",
        password_hash="hash123",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.commit()
    assert user.tenant_id == tenant.id
    assert user.role == UserRole.ADMIN


@pytest.mark.asyncio
async def test_lead_creation(db_session):
    from src.models import Tenant, Lead, Channel, LeadStatus
    tenant = Tenant(name="Test Corp")
    db_session.add(tenant)
    await db_session.flush()

    lead = Lead(
        tenant_id=tenant.id,
        customer_name="Acme Inc",
        channel=Channel.EMAIL,
        status=LeadStatus.NEW,
    )
    db_session.add(lead)
    await db_session.commit()
    assert lead.customer_name == "Acme Inc"


@pytest.mark.asyncio
async def test_message_creation(db_session):
    from src.models import Tenant, Lead, Message, Channel, MessageDirection
    tenant = Tenant(name="Test Corp")
    db_session.add(tenant)
    await db_session.flush()

    lead = Lead(tenant_id=tenant.id, customer_name="Acme Inc", channel=Channel.WEB)
    db_session.add(lead)
    await db_session.flush()

    msg = Message(
        tenant_id=tenant.id,
        lead_id=lead.id,
        sender="customer@acme.com",
        content="Hi, I need a quote for 500 units.",
        direction=MessageDirection.INBOUND,
        channel="email",
    )
    db_session.add(msg)
    await db_session.commit()
    assert msg.lead_id == lead.id


@pytest.mark.asyncio
async def test_relationship_traversal(db_session):
    """Lead has messages, messages belong to lead."""
    from src.models import Tenant, Lead, Message, Channel, MessageDirection
    tenant = Tenant(name="Test Corp")
    db_session.add(tenant)
    await db_session.flush()

    lead = Lead(tenant_id=tenant.id, customer_name="Buyer", channel=Channel.WEB)
    db_session.add(lead)
    await db_session.flush()

    msg1 = Message(tenant_id=tenant.id, lead_id=lead.id, sender="buyer",
                   content="Hi", direction=MessageDirection.INBOUND, channel="web")
    msg2 = Message(tenant_id=tenant.id, lead_id=lead.id, sender="rep",
                   content="Hello!", direction=MessageDirection.OUTBOUND, channel="web")
    db_session.add_all([msg1, msg2])
    await db_session.commit()

    # Re-fetch with eager loading to test relationship
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    result = await db_session.execute(
        select(Lead).where(Lead.id == lead.id).options(selectinload(Lead.messages))
    )
    lead = result.scalar_one()
    assert len(lead.messages) == 2
    assert lead.messages[0].content == "Hi"
    assert lead.messages[1].content == "Hello!"
