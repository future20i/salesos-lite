from fastapi import Request, HTTPException
from sqlalchemy import text
from src.database import AsyncSessionLocal


async def tenant_context_middleware(request: Request, call_next):
    """Extract tenant_id from request state, set PG runtime parameter for RLS."""
    # Public endpoints skip tenant context
    public_paths = ["/api/health", "/api/auth/register", "/api/auth/login", "/api/inbox/incoming"]
    if request.url.path in public_paths:
        return await call_next(request)

    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Tenant context required")

    # Set PG runtime parameter for RLS
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        await session.commit()

    response = await call_next(request)
    return response
