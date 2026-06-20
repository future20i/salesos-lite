"""M5: Create quotations table."""
import asyncio
from sqlalchemy import text
from src.database import engine

async def main():
    async with engine.begin() as conn:
        await conn.run_sync(_run_migration)
        print("✅ quotations table created + RLS enabled")

def _run_migration(sync_conn):
    sync_conn.execute(text("""
        CREATE TABLE IF NOT EXISTS quotations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            lead_id UUID NOT NULL REFERENCES leads(id),
            source_message_id UUID REFERENCES messages(id),
            product_name VARCHAR(512) NOT NULL,
            quantity FLOAT,
            unit VARCHAR(64),
            unit_price FLOAT,
            total FLOAT,
            currency VARCHAR(8) NOT NULL DEFAULT 'USD',
            validity_days INTEGER,
            incoterm VARCHAR(32),
            port VARCHAR(128),
            payment_terms VARCHAR(128),
            notes TEXT,
            confidence FLOAT NOT NULL DEFAULT 0.0,
            raw_extraction TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_quotations_tenant_id ON quotations(tenant_id)"))
    sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_quotations_lead_id ON quotations(lead_id)"))
    sync_conn.execute(text("ALTER TABLE quotations ENABLE ROW LEVEL SECURITY"))
    sync_conn.execute(text("DROP POLICY IF EXISTS tenant_isolation ON quotations"))
    sync_conn.execute(text(
        "CREATE POLICY tenant_isolation ON quotations "
        "USING (tenant_id = current_setting('app.current_tenant_id')::uuid)"
    ))
    sync_conn.commit()

if __name__ == "__main__":
    asyncio.run(main())
