from fastapi import Request, HTTPException
from sqlalchemy import text
from src.database import AsyncSessionLocal


async def tenant_context_middleware(request: Request, call_next):
    """Extract tenant_id from request state or JWT, set PG runtime parameter for RLS."""
    # Public endpoints skip tenant context
    public_paths = [
        "/api/health", "/api/auth/register", "/api/auth/login",
        "/api/inbox/incoming", "/", "/favicon.ico",
        "/api/onboarding/state", "/api/onboarding/advance",
        "/api/billing/status",
        "/widget.js", "/pipeline.js",
        "/kanban",  # Static SPA — auth handled client-side via JWT in localStorage
        "/api/whatsapp/webhook",
        "/api/email/connect", "/api/email/callback",
        "/api/inbox/stream",  # SSE: auth via ?token= query param (EventSource can't send headers)
    ]
    if request.url.path in public_paths or request.url.path.startswith(("/api/auth/", "/static/")):
        return await call_next(request)

    # Try to get tenant_id from request.state (set by get_current_user dependency)
    tenant_id = getattr(request.state, "tenant_id", None)

    # If not set yet, try to extract from JWT in Authorization header or ?token= query param
    if tenant_id is None:
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            # SSE / EventSource can't send headers — fall back to ?token= query param
            token = request.query_params.get("token")

        if token:
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

    # Check subscription status — block expired tenants
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            await session.commit()
    except Exception:
        # Don't poison the connection pool — let the route handle auth
        pass

    # Optional: subscription gate for expired accounts
    # (deferred to route-level checks for now to keep middleware fast)

    response = await call_next(request)
    return response
