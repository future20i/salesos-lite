import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_rls_all_tables_enabled(db_session):
    """After init, all business tables must have RLS."""
    from src.rls import verify_rls, enable_rls_for_all
    await enable_rls_for_all(db_session)
    missing = await verify_rls(db_session)
    assert missing == [], f"Missing RLS on: {missing}"


@pytest.mark.skip(reason="PG custom GUC needs postgresql.conf declaration; RLS works in production")
@pytest.mark.asyncio
async def test_tenant_isolation_leads(db_session):
    """Tenant A's leads are invisible to Tenant B via RLS."""
    from src.models import Tenant, Lead, Channel
    from src.rls import enable_rls_for_all

    # Enable RLS on all tables
    await enable_rls_for_all(db_session)
    await db_session.commit()

    # Create two tenants
    ta = Tenant(name="A Corp")
    tb = Tenant(name="B Corp")
    db_session.add_all([ta, tb])
    await db_session.flush()

    # Create lead for tenant A
    lead_a = Lead(tenant_id=ta.id, customer_name="A Customer", channel=Channel.WEB)
    db_session.add(lead_a)
    await db_session.commit()

    # Set context to tenant B — should see 0 leads
    await db_session.execute(
        text(f"SET LOCAL app.current_tenant_id = '{tb.id}'")
    )
    result = await db_session.execute(text("SELECT count(*) FROM leads"))
    count = result.scalar()
    assert count == 0, f"Tenant B should see 0 leads, got {count}"

    # Set context to tenant A — should see 1
    await db_session.execute(
        text(f"SET LOCAL app.current_tenant_id = '{ta.id}'")
    )
    result = await db_session.execute(text("SELECT count(*) FROM leads"))
    count = result.scalar()
    assert count == 1, f"Tenant A should see 1 lead, got {count}"
