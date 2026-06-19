from fastapi import Request, HTTPException
from sqlalchemy import text
from src.database import AsyncSessionLocal


async def tenant_context_middleware(request: Request, call_next):
    """Extract tenant_id from request state or JWT, set PG runtime parameter for RLS."""
    # Public endpoints skip tenant context
    public_paths = ["/api/health", "/api/auth/register", "/api/auth/login", "/api/inbox/incoming"]
    if request.url.path in public_paths:
        return await call_next(request)

    # Try to get tenant_id from request.state (set by get_current_user dependency)
    tenant_id = getattr(request.state, "tenant_id", None)

    # If not set yet, try to extract from JWT in Authorization header
    if tenant_id is None:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                from src.auth import decode_token
                payload = decode_token(token)
                tenant_id = payload.get("tenant_id")
                if tenant_id:
                    request.state.tenant_id = tenant_id
            except HTTPException:
                pass  # will be handled by the route's get_current_user dependency

    # If still no tenant context, raise 401 (but let the middleware pass through
    # for routes that have their own auth — the downstream dependency will catch it)
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
