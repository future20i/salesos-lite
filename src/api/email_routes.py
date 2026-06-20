"""Email OAuth2 integration routes — Gmail (Google Identity) and Outlook (Microsoft Graph)."""

import os
import uuid
import urllib.parse
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from src.database import get_db
from src.auth import get_current_user
from src.models import (
    User, UserRole,
    Lead, LeadStatus, Channel,
    Message, MessageDirection,
    AIJob, AIJobStatus,
    EmailConnection, EmailProvider,
)
from src.sse import sse_broadcast

router = APIRouter(prefix="/api/email", tags=["email"])

# ── Environment ──────────────────────────────────────────────────────

GMAIL_CLIENT_ID = os.environ.get("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.environ.get("GMAIL_CLIENT_SECRET", "")

OUTLOOK_CLIENT_ID = os.environ.get("OUTLOOK_CLIENT_ID", "")
OUTLOOK_CLIENT_SECRET = os.environ.get("OUTLOOK_CLIENT_SECRET", "")

REDIRECT_URI = os.environ.get(
    "EMAIL_REDIRECT_URI",
    "http://198.199.123.43:8001/api/email/callback",
)

# ── OAuth 2.0 endpoint definitions ──────────────────────────────────

OAUTH_CONFIG = {
    "gmail": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/userinfo.email",
        ],
    },
    "outlook": {
        "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": [
            "offline_access",
            "User.Read",
            "Mail.Read",
            "Mail.Send",
        ],
    },
}


# ── Schemas ─────────────────────────────────────────────────────────

class EmailConnectionResponse(BaseModel):
    id: str
    provider: str
    email_address: str
    is_active: bool
    created_at: str


class EmailMessageItem(BaseModel):
    id: str
    subject: str
    from_email: str
    from_name: str
    snippet: str
    received_at: str


class IngestResult(BaseModel):
    new_leads: int
    new_messages: int
    new_ai_jobs: int
    emails: list[EmailMessageItem]


# ── Internal helpers ────────────────────────────────────────────────

def _build_authorize_url(provider: str, state: str) -> str:
    """Build the OAuth2 authorisation URL for the given provider."""
    cfg = OAUTH_CONFIG[provider]
    params = {
        "client_id": (GMAIL_CLIENT_ID if provider == "gmail" else OUTLOOK_CLIENT_ID),
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(cfg["scopes"]),
        "state": state,
        "access_type": "offline" if provider == "gmail" else None,
        "prompt": "consent",
    }
    # Gmail uses access_type=offline; Outlook uses offline_access scope already
    if provider == "gmail":
        params["access_type"] = "offline"
        params["prompt"] = "consent"
    else:
        params.pop("access_type", None)
        params.pop("prompt", None)
    # Remove None values
    clean_params = {k: v for k, v in params.items() if v is not None}
    return f"{cfg['authorize_url']}?{urllib.parse.urlencode(clean_params)}"


def _provider_client_secret(provider: str) -> str:
    if provider == "gmail":
        return GMAIL_CLIENT_SECRET
    elif provider == "outlook":
        return OUTLOOK_CLIENT_SECRET
    raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")


async def _exchange_code(provider: str, code: str) -> dict:
    """Exchange an authorisation code for tokens via httpx."""
    cfg = OAUTH_CONFIG[provider]
    client_id = GMAIL_CLIENT_ID if provider == "gmail" else OUTLOOK_CLIENT_ID
    client_secret = _provider_client_secret(provider)

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(cfg["token_url"], data=data)
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Token exchange failed: {resp.status_code} {resp.text}",
        )
    return resp.json()


async def _refresh_access_token(conn: EmailConnection, db: AsyncSession) -> str:
    """Refresh an expired access token using the stored refresh token."""
    if not conn.refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token available")

    cfg = OAUTH_CONFIG[conn.provider.value]
    client_id = GMAIL_CLIENT_ID if conn.provider == EmailProvider.GMAIL else OUTLOOK_CLIENT_ID
    client_secret = _provider_client_secret(conn.provider.value)

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": conn.refresh_token,
        "grant_type": "refresh_token",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(cfg["token_url"], data=data)
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Token refresh failed: {resp.status_code} {resp.text}",
        )

    token_data = resp.json()
    new_access_token = token_data.get("access_token", conn.access_token)
    expires_in = token_data.get("expires_in", 3600)
    conn.access_token = new_access_token
    conn.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    await db.commit()
    return new_access_token


async def _get_valid_token(conn: EmailConnection, db: AsyncSession) -> str:
    """Return a valid (possibly refreshed) access token."""
    if conn.token_expires_at and datetime.now(timezone.utc) >= conn.token_expires_at:
        return await _refresh_access_token(conn, db)
    return conn.access_token


async def _get_gmail_profile(token: str) -> dict:
    """Fetch the authenticated Gmail user's email address."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Gmail profile fetch failed: {resp.status_code} {resp.text}",
        )
    return resp.json()


async def _get_outlook_profile(token: str) -> dict:
    """Fetch the authenticated Outlook user's email address."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Outlook profile fetch failed: {resp.status_code} {resp.text}",
        )
    return resp.json()


async def _fetch_gmail_inbox(
    token: str, limit: int = 20
) -> list[dict]:
    """Fetch recent Gmail inbox messages (metadata + snippet)."""
    async with httpx.AsyncClient() as client:
        # List recent messages from INBOX (not SENT, not SPAM, not TRASH)
        list_resp = await client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            params={
                "q": "in:inbox -in:spam -in:trash",
                "maxResults": limit,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    if list_resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Gmail list failed: {list_resp.status_code} {list_resp.text}",
        )

    data = list_resp.json()
    messages_data = data.get("messages", [])

    results = []
    async with httpx.AsyncClient() as client:
        for msg_ref in messages_data:
            msg_resp = await client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_ref['id']}",
                params={"format": "metadata", "metadataHeaders": "From"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if msg_resp.status_code != 200:
                continue
            msg = msg_resp.json()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            results.append({
                "id": msg["id"],
                "thread_id": msg.get("threadId", ""),
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", "(no subject)"),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
                "internal_date": msg.get("internalDate", "0"),
            })
    return results


async def _fetch_outlook_inbox(
    token: str, limit: int = 20
) -> list[dict]:
    """Fetch recent Outlook inbox messages via Microsoft Graph."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages",
            params={
                "$top": limit,
                "$orderby": "receivedDateTime desc",
                "$select": "id,subject,from,receivedDateTime,bodyPreview,conversationId",
                "$filter": "isDraft eq false",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Outlook inbox fetch failed: {resp.status_code} {resp.text}",
        )

    data = resp.json()
    results = []
    for msg in data.get("value", []):
        from_data = msg.get("from", {})
        email_address = from_data.get("emailAddress", {}) if from_data else {}
        results.append({
            "id": msg["id"],
            "conversation_id": msg.get("conversationId", ""),
            "from": email_address.get("address", ""),
            "from_name": email_address.get("name", ""),
            "subject": msg.get("subject", "(no subject)"),
            "received_date": msg.get("receivedDateTime", ""),
            "snippet": msg.get("bodyPreview", ""),
        })
    return results


def _parse_email_address(raw_from: str) -> tuple[str, str]:
    """Parse a raw From header into (name, email)."""
    # e.g. "John Doe <john@example.com>" or just "john@example.com"
    if "<" in raw_from and ">" in raw_from:
        name = raw_from.split("<")[0].strip().strip('"')
        email = raw_from.split("<")[1].split(">")[0].strip()
        return name, email
    return "", raw_from.strip()


# ── Route: GET /api/email/connect ───────────────────────────────────
# Public — redirects to the OAuth provider's consent page.

@router.get("/connect")
async def email_connect(
    provider: str = Query(..., description="gmail or outlook"),
    tenant_id: str = Query(..., description="Tenant ID to attach this connection to"),
):
    """Initiate OAuth2 flow. Redirects user to Gmail or Outlook consent page."""
    provider = provider.lower()
    if provider not in ("gmail", "outlook"):
        raise HTTPException(status_code=400, detail="Provider must be 'gmail' or 'outlook'")

    # Validate tenant_id is a valid UUID
    try:
        uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant_id")

    # Use tenant_id as part of the state to recover it on callback
    state = tenant_id

    authorize_url = _build_authorize_url(provider, state)
    # Return 302-style redirect info (the frontend will redirect)
    return {"redirect_url": authorize_url}


# ── Route: GET /api/email/callback ──────────────────────────────────
# Public — OAuth provider redirects here with a code.

@router.get("/callback")
async def email_callback(
    request: Request,
    provider: str = Query(..., description="gmail or outlook"),
    code: str = Query(""),
    state: str = Query(""),
    error: str = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Handle OAuth2 callback from Gmail or Microsoft.

    Exchanges the authorisation code for tokens, fetches the user's email
    address, and stores the EmailConnection in the database.
    """
    if error:
        raise HTTPException(
            status_code=400,
            detail=f"OAuth provider returned error: {error}",
        )

    provider = provider.lower()
    if provider not in ("gmail", "outlook"):
        raise HTTPException(status_code=400, detail="Provider must be 'gmail' or 'outlook'")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorisation code")

    # Recover tenant_id from state
    try:
        tenant_id = uuid.UUID(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid state — expected tenant UUID")

    # Verify tenant exists
    from src.models.tenant import Tenant
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Exchange code for tokens
    token_data = await _exchange_code(provider, code)

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)
    token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # Fetch user's email address from the provider
    email_address = ""
    if provider == "gmail":
        profile = await _get_gmail_profile(access_token)
        email_address = profile.get("emailAddress", "")
    else:
        profile = await _get_outlook_profile(access_token)
        email_address = profile.get("mail", "") or profile.get("userPrincipalName", "")

    if not email_address:
        raise HTTPException(status_code=502, detail="Could not determine email address from provider")

    # Check for existing connection
    result = await db.execute(
        select(EmailConnection).where(
            EmailConnection.tenant_id == tenant_id,
            EmailConnection.provider == provider,
            EmailConnection.email_address == email_address,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update existing connection
        existing.access_token = access_token
        if refresh_token:
            existing.refresh_token = refresh_token
        existing.token_expires_at = token_expires_at
        existing.is_active = True
        existing.updated_at = datetime.now(timezone.utc)
        conn = existing
    else:
        # Create new connection
        conn = EmailConnection(
            tenant_id=tenant_id,
            provider=EmailProvider(provider),
            email_address=email_address,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at,
            is_active=True,
        )
        db.add(conn)

    await db.commit()
    await db.refresh(conn)

    return {
        "status": "connected",
        "connection": EmailConnectionResponse(
            id=str(conn.id),
            provider=conn.provider.value,
            email_address=conn.email_address,
            is_active=conn.is_active,
            created_at=conn.created_at.isoformat(),
        ),
    }


# ── Route: GET /api/email/connections ───────────────────────────────
# Lists all email connections for the current user's tenant.

@router.get("/connections")
async def list_connections(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all email connections for the current tenant."""
    result = await db.execute(
        select(EmailConnection).where(
            EmailConnection.tenant_id == current_user.tenant_id,
            EmailConnection.is_active == True,
        )
    )
    connections = result.scalars().all()
    return [
        EmailConnectionResponse(
            id=str(c.id),
            provider=c.provider.value,
            email_address=c.email_address,
            is_active=c.is_active,
            created_at=c.created_at.isoformat(),
        )
        for c in connections
    ]


# ── Route: DELETE /api/email/connections/{connection_id} ────────────

@router.delete("/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deactivate an email connection."""
    result = await db.execute(
        select(EmailConnection).where(
            EmailConnection.id == connection_id,
            EmailConnection.tenant_id == current_user.tenant_id,
        )
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(status_code=404, detail="Email connection not found")

    conn.is_active = False
    await db.commit()


# ── Route: GET /api/email/inbox ─────────────────────────────────────
# Fetches new emails from the connected provider, creates leads + messages,
# enqueues AIJobs, and returns the results.

@router.get("/inbox")
async def fetch_inbox(
    provider: str = Query(..., description="gmail or outlook"),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch recent inbox emails from the connected provider.

    For each new email (not previously seen), it will:
    - Find or create a Lead by sender email
    - Create an inbound Message
    - Enqueue an AIJob for classification
    """
    provider = provider.lower()
    if provider not in ("gmail", "outlook"):
        raise HTTPException(status_code=400, detail="Provider must be 'gmail' or 'outlook'")

    # Find an active connection for this provider
    result = await db.execute(
        select(EmailConnection).where(
            EmailConnection.tenant_id == current_user.tenant_id,
            EmailConnection.provider == provider,
            EmailConnection.is_active == True,
        ).limit(1)
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active {provider} connection found. Connect at GET /api/email/connect?provider={provider}&tenant_id={current_user.tenant_id}",
        )

    # Get a valid access token
    token = await _get_valid_token(conn, db)

    # Fetch emails
    if provider == "gmail":
        raw_emails = await _fetch_gmail_inbox(token, limit)
    else:
        raw_emails = await _fetch_outlook_inbox(token, limit)

    # Get existing channel_message_ids to avoid duplicates (scope to tenant)
    existing_ids_result = await db.execute(
        select(Message.channel_message_id).where(
            Message.tenant_id == tenant_id,
            Message.channel == "email",
            Message.channel_message_id.isnot(None),
        )
    )
    existing_ids = set(existing_ids_result.scalars().all())

    new_leads = 0
    new_messages = 0
    new_ai_jobs = 0
    ingested: list[EmailMessageItem] = []

    tenant_id = current_user.tenant_id

    for raw in raw_emails:
        # Determine unique message ID
        channel_msg_id = raw["id"]
        if channel_msg_id in existing_ids:
            continue  # already ingested

        # Parse sender
        if provider == "gmail":
            from_name, from_email = _parse_email_address(raw["from"])
            subject = raw.get("subject", "(no subject)")
            snippet = raw.get("snippet", "")
            received_date = raw.get("internal_date", "0")
            # Convert Unix ms timestamp to ISO
            try:
                received_dt = datetime.fromtimestamp(
                    int(received_date) / 1000, tz=timezone.utc
                )
            except (ValueError, OSError):
                received_dt = datetime.now(timezone.utc)
            received_str = received_dt.isoformat()
        else:
            from_email = raw.get("from", "")
            from_name = raw.get("from_name", "")
            subject = raw.get("subject", "(no subject)")
            snippet = raw.get("snippet", "")
            received_str = raw.get("received_date", "")

        if not from_email:
            continue  # can't process without a sender email

        customer_name = from_name if from_name else from_email.split("@")[0]

        # Find or create Lead
        result = await db.execute(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.channel == Channel.EMAIL,
                Lead.customer_name == from_email,  # use email as unique customer_name for email channel
            ).limit(1)
        )
        lead = result.scalar_one_or_none()

        if lead is None:
            lead = Lead(
                tenant_id=tenant_id,
                customer_name=from_email,
                channel=Channel.EMAIL,
                status=LeadStatus.NEW,
                unread=True,
                last_activity_at=datetime.now(timezone.utc),
            )
            db.add(lead)
            await db.flush()
            new_leads += 1

        # Build content from subject + snippet
        content = f"Subject: {subject}\n\n{snippet}"

        # Create Message
        message = Message(
            tenant_id=tenant_id,
            lead_id=lead.id,
            sender=from_email,
            content=content,
            direction=MessageDirection.INBOUND,
            channel="email",
            channel_message_id=channel_msg_id,
        )
        db.add(message)
        await db.flush()
        new_messages += 1

        # Enqueue AIJob
        ai_job = AIJob(
            tenant_id=tenant_id,
            lead_id=lead.id,
            message_id=message.id,
            job_type="classify",
            status=AIJobStatus.PENDING,
        )
        db.add(ai_job)
        new_ai_jobs += 1

        # Update lead last_activity_at
        lead.last_activity_at = datetime.now(timezone.utc)
        lead.unread = True

        # Track for response
        ingested.append(EmailMessageItem(
            id=channel_msg_id,
            subject=subject,
            from_email=from_email,
            from_name=customer_name,
            snippet=snippet[:200],
            received_at=received_str,
        ))

        existing_ids.add(channel_msg_id)

    await db.commit()

    # Broadcast new messages via SSE
    if ingested:
        await sse_broadcast(
            str(tenant_id),
            {"type": "email_ingested", "count": len(ingested)},
        )

    return IngestResult(
        new_leads=new_leads,
        new_messages=new_messages,
        new_ai_jobs=new_ai_jobs,
        emails=ingested,
    )
