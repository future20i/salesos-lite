"""Row-Level Security — every business table must enable RLS."""

from sqlalchemy import text

AUDIT_QUERY = """
SELECT relname FROM pg_class
WHERE relkind = 'r'
  AND relrowsecurity = false
  AND relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
  AND relname NOT LIKE 'pg_%'
  AND relname NOT LIKE 'alembic_%'
  AND relname != 'tenants';  -- root table, no tenant_id column
"""

POLICY_SQL = """
CREATE POLICY tenant_isolation ON {table}
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
"""

BUSINESS_TABLES = [
    "users", "leads", "messages", "ai_jobs",
    "approvals", "canned_responses", "subscriptions",
]


async def enable_rls_for_all(conn):
    """Enable RLS + create policies on all business tables (idempotent)."""
    for table in BUSINESS_TABLES:
        await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        await conn.execute(text(f"DROP POLICY IF EXISTS tenant_isolation ON {table}"))
        await conn.execute(text(POLICY_SQL.format(table=table)))


async def verify_rls(conn) -> list[str]:
    """Return list of tables WITHOUT RLS. Empty = pass."""
    result = await conn.execute(text(AUDIT_QUERY))
    return [row[0] for row in result]
