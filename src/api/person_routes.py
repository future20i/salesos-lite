"""PersonProfile CRUD routes — 人脉画像 (personal relationship profiles).

4-layer depth model:
  Layer 1: Business needs (team-shared) — from Lead/Opportunity context
  Layer 2: Personal portrait (team-shared) — 麦凯66 core
  Layer 3: Decision drivers (creator + full access only, ENCRYPTED at rest)
  Layer 4: Influence levers (creator + full access only, ENCRYPTED at rest)

Endpoints:
  GET    /api/persons           — List profiles (filters: lead_id, opportunity_id)
  GET    /api/persons/{id}      — Get profile detail
  POST   /api/persons           — Create profile (returns 201)
  PATCH  /api/persons/{id}      — Update profile (creator only)
  GET    /api/persons/{id}/briefing — LLM-generated pre-battle briefing
  POST   /api/persons/{id}/grant    — Grant access to another user
"""

import uuid
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from cryptography.fernet import Fernet

from src.database import get_db
from src.auth import get_current_user
from src.models import PersonProfile, User
from src.llm_client import llm_complete

router = APIRouter(prefix="/api/persons", tags=["persons"])

# ── Fields that are encrypted at rest (Layer 3 + Layer 4) ────────────────
_ENCRYPTED_FIELDS = {
    "core_fear",
    "core_ambition",
    "org_situation",
    "trust_foundation",
    "leverage_points",
    "relationship_activities",
}

# ── Layer 1+2 fields (always safe to return to team members) ─────────────
_LAYER12_FIELDS = {
    "full_name", "title", "birthday", "hometown", "education",
    "personality_tags", "spouse_name", "spouse_occupation",
    "children_info", "interests", "relationship_depth",
    "last_personal_touch_at",
}


# ═══════════════════════════════════════════════════════════════════════
#  Encryption helpers
# ═══════════════════════════════════════════════════════════════════════

def _has_full_access(profile: PersonProfile, current_user: User) -> bool:
    """Check if current_user has full access (can decrypt layer 3-4)."""
    if profile.created_by == current_user.id:
        return True
    access_list = profile.access_list or []
    for entry in access_list:
        if entry.get("user_id") == str(current_user.id) and entry.get("access_level") == "full":
            return True
    return False


def _encrypt_value(value: str, encryption_key: str) -> str:
    """Encrypt a string value with the user's Fernet key, prefix with ENC:."""
    f = Fernet(encryption_key.encode())
    encrypted = f.encrypt(value.encode()).decode()
    return f"ENC:{encrypted}"


def _decrypt_value(enc_value: str, encryption_key: str) -> str:
    """Decrypt an ENC: prefixed string with the user's Fernet key."""
    if enc_value.startswith("ENC:"):
        raw = enc_value[4:]
        f = Fernet(encryption_key.encode())
        return f.decrypt(raw.encode()).decode()
    return enc_value  # not encrypted, return as-is


def _encrypt_layer34_fields(profile: PersonProfile, encryption_key: str, field_values: dict, existing_encrypted: set | None = None):
    """Encrypt layer 3-4 fields and update encrypted_fields list.

    field_values: dict of field_name → plaintext_value (only for fields that should be set)
    existing_encrypted: set of field names already encrypted (for update merges)
    """
    encrypted_set = existing_encrypted or set()
    for field_name, value in field_values.items():
        if field_name in _ENCRYPTED_FIELDS and value is not None:
            setattr(profile, field_name, _encrypt_value(value, encryption_key))
            encrypted_set.add(field_name)
    profile.encrypted_fields = sorted(encrypted_set)


# ═══════════════════════════════════════════════════════════════════════
#  Pydantic Schemas
# ═══════════════════════════════════════════════════════════════════════

class PersonProfileCreate(BaseModel):
    """Schema for creating a new person profile."""
    full_name: str
    title: str | None = None
    lead_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    # Layer 2
    birthday: str | None = None
    hometown: str | None = None
    education: str | None = None
    personality_tags: list[str] | None = None
    spouse_name: str | None = None
    spouse_occupation: str | None = None
    children_info: list[dict] | None = None
    interests: list[dict] | None = None
    # Layer 3 (encrypted)
    core_fear: str | None = None
    core_ambition: str | None = None
    org_situation: str | None = None
    trust_foundation: str | None = None
    # Layer 4 (encrypted)
    leverage_points: list[dict] | None = None
    relationship_activities: list[dict] | None = None
    # Relationship
    relationship_depth: int | None = None


class PersonProfileUpdate(BaseModel):
    """Schema for patching an existing person profile. All fields optional."""
    full_name: str | None = None
    title: str | None = None
    lead_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    # Layer 2
    birthday: str | None = None
    hometown: str | None = None
    education: str | None = None
    personality_tags: list[str] | None = None
    spouse_name: str | None = None
    spouse_occupation: str | None = None
    children_info: list[dict] | None = None
    interests: list[dict] | None = None
    # Layer 3 (encrypted)
    core_fear: str | None = None
    core_ambition: str | None = None
    org_situation: str | None = None
    trust_foundation: str | None = None
    # Layer 4 (encrypted)
    leverage_points: list[dict] | None = None
    relationship_activities: list[dict] | None = None
    # Relationship
    relationship_depth: int | None = None


class PersonProfileBriefResponse(BaseModel):
    """Layer 1+2 only — safe for team-wide sharing."""
    id: str
    lead_id: str | None = None
    opportunity_id: str | None = None
    full_name: str | None = None
    title: str | None = None
    birthday: str | None = None
    hometown: str | None = None
    education: str | None = None
    personality_tags: list | None = None
    spouse_name: str | None = None
    spouse_occupation: str | None = None
    children_info: list | None = None
    interests: list | None = None
    relationship_depth: int | None = None
    last_personal_touch_at: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    model_config = {"from_attributes": True}


class PersonProfileResponse(BaseModel):
    """Full response — layer 3-4 included only for authorized users."""
    id: str
    tenant_id: str
    lead_id: str | None = None
    opportunity_id: str | None = None
    # Layer 2
    full_name: str | None = None
    title: str | None = None
    birthday: str | None = None
    hometown: str | None = None
    education: str | None = None
    personality_tags: list | None = None
    spouse_name: str | None = None
    spouse_occupation: str | None = None
    children_info: list | None = None
    interests: list | None = None
    # Layer 3
    core_fear: str | None = None
    core_ambition: str | None = None
    org_situation: str | None = None
    trust_foundation: str | None = None
    # Layer 4
    leverage_points: list | None = None
    relationship_activities: list | None = None
    # Relationship
    relationship_depth: int | None = None
    last_personal_touch_at: str | None = None
    # Metadata
    encrypted_fields: list | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    model_config = {"from_attributes": True}


class GrantAccessRequest(BaseModel):
    """Schema for granting access to another user."""
    user_id: uuid.UUID
    access_level: str  # "full" or "layer2_only"


class BriefingResponse(BaseModel):
    """Pre-battle briefing generated by LLM."""
    profile_id: str
    full_name: str | None = None
    briefing: str

def _profile_to_dict(
    profile: PersonProfile,
    current_user: User,
) -> dict:
    """Convert PersonProfile ORM object to a plain dict for intel engine consumption."""
    full_access = _has_full_access(profile, current_user)

    data: dict = {
        "full_name": profile.full_name,
        "title": profile.title,
        "birthday": profile.birthday,
        "hometown": profile.hometown,
        "education": profile.education,
        "personality_tags": profile.personality_tags,
        "spouse_name": profile.spouse_name,
        "spouse_occupation": profile.spouse_occupation,
        "children_info": profile.children_info,
        "interests": profile.interests,
        "relationship_depth": profile.relationship_depth,
        "last_personal_touch_at": str(profile.last_personal_touch_at) if profile.last_personal_touch_at else None,
    }

    if full_access and current_user.encryption_key:
        data["core_fear"] = _decrypt_value(profile.core_fear or "", current_user.encryption_key) if profile.core_fear else None
        data["core_ambition"] = _decrypt_value(profile.core_ambition or "", current_user.encryption_key) if profile.core_ambition else None
        data["org_situation"] = _decrypt_value(profile.org_situation or "", current_user.encryption_key) if profile.org_situation else None
        data["trust_foundation"] = _decrypt_value(profile.trust_foundation or "", current_user.encryption_key) if profile.trust_foundation else None
        data["leverage_points"] = profile.leverage_points
        data["relationship_activities"] = profile.relationship_activities

    return data




def _profile_to_response(
    profile: PersonProfile,
    current_user: User,
) -> PersonProfileResponse:
    """Convert PersonProfile ORM object to PersonProfileResponse,
    decrypting layer 3-4 fields for authorized users."""
    full_access = _has_full_access(profile, current_user)

    kwargs: dict = {
        "id": str(profile.id),
        "tenant_id": str(profile.tenant_id),
        "lead_id": str(profile.lead_id) if profile.lead_id else None,
        "opportunity_id": str(profile.opportunity_id) if profile.opportunity_id else None,
        # Layer 2
        "full_name": profile.full_name,
        "title": profile.title,
        "birthday": profile.birthday,
        "hometown": profile.hometown,
        "education": profile.education,
        "personality_tags": profile.personality_tags,
        "spouse_name": profile.spouse_name,
        "spouse_occupation": profile.spouse_occupation,
        "children_info": profile.children_info,
        "interests": profile.interests,
        # Relationship
        "relationship_depth": profile.relationship_depth,
        "last_personal_touch_at": str(profile.last_personal_touch_at) if profile.last_personal_touch_at else None,
        # Metadata
        "encrypted_fields": profile.encrypted_fields,
        "created_by": str(profile.created_by) if profile.created_by else None,
        "created_at": str(profile.created_at) if profile.created_at else None,
        "updated_at": str(profile.updated_at) if profile.updated_at else None,
    }

    # Layer 3-4: decrypt for authorized users
    if full_access and current_user.encryption_key:
        kwargs["core_fear"] = _decrypt_value(profile.core_fear or "", current_user.encryption_key) if profile.core_fear else None
        kwargs["core_ambition"] = _decrypt_value(profile.core_ambition or "", current_user.encryption_key) if profile.core_ambition else None
        kwargs["org_situation"] = _decrypt_value(profile.org_situation or "", current_user.encryption_key) if profile.org_situation else None
        kwargs["trust_foundation"] = _decrypt_value(profile.trust_foundation or "", current_user.encryption_key) if profile.trust_foundation else None
        kwargs["leverage_points"] = profile.leverage_points  # JSON already stored encrypted
        kwargs["relationship_activities"] = profile.relationship_activities
    else:
        kwargs["core_fear"] = None
        kwargs["core_ambition"] = None
        kwargs["org_situation"] = None
        kwargs["trust_foundation"] = None
        kwargs["leverage_points"] = None
        kwargs["relationship_activities"] = None

    return PersonProfileResponse(**kwargs)


# ═══════════════════════════════════════════════════════════════════════
#  Routes
# ═══════════════════════════════════════════════════════════════════════

@router.get("/")
async def list_persons(
    lead_id: uuid.UUID | None = Query(None, description="Filter by lead"),
    opportunity_id: uuid.UUID | None = Query(None, description="Filter by opportunity"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PersonProfileResponse]:
    """List person profiles for the current tenant.

    - Returns layer 1+2 data for all team members.
    - Layer 3-4 only returned if current_user is creator or has full access.
    """
    stmt = select(PersonProfile).where(
        PersonProfile.tenant_id == current_user.tenant_id
    )

    if lead_id is not None:
        stmt = stmt.where(PersonProfile.lead_id == lead_id)
    if opportunity_id is not None:
        stmt = stmt.where(PersonProfile.opportunity_id == opportunity_id)

    stmt = stmt.order_by(PersonProfile.updated_at.desc())

    result = await db.execute(stmt)
    profiles = result.scalars().all()

    return [_profile_to_response(p, current_user) for p in profiles]


@router.get("/{profile_id}")
async def get_person(
    profile_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonProfileResponse:
    """Get a single person profile with layer-based access control."""
    stmt = select(PersonProfile).where(
        PersonProfile.id == profile_id,
        PersonProfile.tenant_id == current_user.tenant_id,
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Person profile not found",
        )

    return _profile_to_response(profile, current_user)


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_person(
    body: PersonProfileCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonProfileResponse:
    """Create a new person profile. Encrypts layer 3-4 fields at rest."""
    if not current_user.encryption_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no encryption key configured. Please set up encryption in your account settings.",
        )

    profile = PersonProfile(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        lead_id=body.lead_id,
        opportunity_id=body.opportunity_id,
        full_name=body.full_name,
        title=body.title,
        birthday=body.birthday,
        hometown=body.hometown,
        education=body.education,
        personality_tags=body.personality_tags,
        spouse_name=body.spouse_name,
        spouse_occupation=body.spouse_occupation,
        children_info=body.children_info,
        interests=body.interests,
        relationship_depth=body.relationship_depth,
    )

    # Encrypt layer 3-4 fields
    encrypted_values = {}
    for name in _ENCRYPTED_FIELDS:
        value = getattr(body, name, None)
        if value is not None:
            encrypted_values[name] = value

    _encrypt_layer34_fields(profile, current_user.encryption_key, encrypted_values)

    db.add(profile)
    await db.commit()
    await db.refresh(profile)

    return _profile_to_response(profile, current_user)


@router.patch("/{profile_id}")
async def update_person(
    profile_id: uuid.UUID,
    body: PersonProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PersonProfileResponse:
    """Update a person profile. Only the creator can update.

    Layer 3-4 fields are re-encrypted if provided.
    """
    stmt = select(PersonProfile).where(
        PersonProfile.id == profile_id,
        PersonProfile.tenant_id == current_user.tenant_id,
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Person profile not found",
        )

    # Only creator can update
    if profile.created_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the creator of this profile can update it",
        )

    # Apply updates for layer 1-2 fields
    if body.full_name is not None:
        profile.full_name = body.full_name
    if body.title is not None:
        profile.title = body.title
    if body.lead_id is not None:
        profile.lead_id = body.lead_id
    if body.opportunity_id is not None:
        profile.opportunity_id = body.opportunity_id
    if body.birthday is not None:
        profile.birthday = body.birthday
    if body.hometown is not None:
        profile.hometown = body.hometown
    if body.education is not None:
        profile.education = body.education
    if body.personality_tags is not None:
        profile.personality_tags = body.personality_tags
    if body.spouse_name is not None:
        profile.spouse_name = body.spouse_name
    if body.spouse_occupation is not None:
        profile.spouse_occupation = body.spouse_occupation
    if body.children_info is not None:
        profile.children_info = body.children_info
    if body.interests is not None:
        profile.interests = body.interests
    if body.relationship_depth is not None:
        profile.relationship_depth = body.relationship_depth

    # Re-encrypt layer 3-4 fields if provided
    if not current_user.encryption_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no encryption key configured",
        )

    # Track which encrypted fields are being updated
    existing_encrypted = set(profile.encrypted_fields or [])
    encrypted_updates = {}
    for name in _ENCRYPTED_FIELDS:
        value = getattr(body, name, None)
        if value is not None:
            encrypted_updates[name] = value

    if encrypted_updates:
        _encrypt_layer34_fields(profile, current_user.encryption_key, encrypted_updates, existing_encrypted)

    await db.commit()
    await db.refresh(profile)

    return _profile_to_response(profile, current_user)


@router.get("/{profile_id}/briefing")
async def get_briefing(
    profile_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BriefingResponse:
    """Generate a pre-battle briefing (战前简报) using LLM.

    Returns a 30-second structured summary:
    - Who they are
    - What they care about
    - Last interaction
    - Personal touch points
    - Suggested approach
    """
    stmt = select(PersonProfile).where(
        PersonProfile.id == profile_id,
        PersonProfile.tenant_id == current_user.tenant_id,
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Person profile not found",
        )

    import asyncio
    from src.intel_engine import generate_briefing, generate_strategy_card
    
    # Get recent interactions for context
    from src.models.interaction_log import InteractionLog
    ix_result = await db.execute(
        select(InteractionLog)
        .where(InteractionLog.person_profile_id == profile_id)
        .order_by(InteractionLog.created_at.desc())
        .limit(5)
    )
    recent_ix = [
        {
            "interaction_type": ix.interaction_type,
            "summary": ix.summary or "",
        }
        for ix in ix_result.scalars().all()
    ]

    # Decrypt layer 3-4 for briefing (creator only)
    person_data = _profile_to_dict(profile, current_user)

    briefing = await generate_briefing(person_data, recent_ix)

    return BriefingResponse(
        profile_id=str(profile.id),
        full_name=profile.full_name,
        briefing=json.dumps(briefing, ensure_ascii=False, indent=2),
    )


@router.get("/{profile_id}/strategy")
async def get_strategy_card(
    profile_id: uuid.UUID,
    opportunity_id: uuid.UUID | None = Query(None, description="Opportunity context"),
    message_id: uuid.UUID | None = Query(None, description="Message context"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate a strategy card (策略伴写) for composing a message.

    Returns: {say, avoid, hooks, tone, reference_points}
    """
    import asyncio
    from src.intel_engine import generate_strategy_card

    stmt = select(PersonProfile).where(
        PersonProfile.id == profile_id,
        PersonProfile.tenant_id == current_user.tenant_id,
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Person profile not found",
        )

    # Get opportunity context
    opp_context = ""
    if opportunity_id:
        from src.models.opportunity import Opportunity
        opp_result = await db.execute(
            select(Opportunity).where(
                Opportunity.id == opportunity_id,
                Opportunity.tenant_id == current_user.tenant_id,
            )
        )
        opp = opp_result.scalar_one_or_none()
        if opp:
            opp_context = f"商机: {opp.name}, 阶段: {opp.stage.value}, 金额: {opp.value or '未知'}"

    # Get message context
    msg_context = ""
    if message_id:
        from src.models.message import Message
        msg_result = await db.execute(
            select(Message).where(
                Message.id == message_id,
                Message.tenant_id == current_user.tenant_id,
            )
        )
        msg = msg_result.scalar_one_or_none()
        if msg:
            msg_context = msg.content[:1000]

    person_data = _profile_to_dict(profile, current_user)
    strategy = await generate_strategy_card(person_data, opp_context, msg_context)

    return strategy


# ═══════════════════════════════════════════════════════════════════════
# B4 — Resource Matching
# ═══════════════════════════════════════════════════════════════════════

@router.get("/recommendations/relationship")
async def get_relationship_recommendations(
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """B4 Resource Matching — recommend relationship-deepening actions.

    Returns up to 20 recommendations sorted by urgency.
    """
    from src.intel_engine import recommend_relationship_actions
    return await recommend_relationship_actions(current_user.tenant_id)


@router.post("/{profile_id}/grant")
async def grant_access(
    profile_id: uuid.UUID,
    body: GrantAccessRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Grant access to a person profile for another user.

    Only the creator of the profile can grant access.
    access_level must be "full" or "layer2_only".
    """
    if body.access_level not in ("full", "layer2_only"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="access_level must be 'full' or 'layer2_only'",
        )

    stmt = select(PersonProfile).where(
        PersonProfile.id == profile_id,
        PersonProfile.tenant_id == current_user.tenant_id,
    )
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Person profile not found",
        )

    # Only creator can grant access
    if profile.created_by != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the creator of this profile can grant access",
        )

    # Build or update access_list
    access_list: list[dict] = list(profile.access_list) if profile.access_list else []

    # Check if user already has an entry; update or append
    user_id_str = str(body.user_id)
    updated = False
    for entry in access_list:
        if entry.get("user_id") == user_id_str:
            entry["access_level"] = body.access_level
            updated = True
            break

    if not updated:
        access_list.append({
            "user_id": user_id_str,
            "access_level": body.access_level,
        })

    profile.access_list = access_list
    await db.commit()
    await db.refresh(profile)

    return {
        "status": "ok",
        "profile_id": str(profile.id),
        "granted_to": user_id_str,
        "access_level": body.access_level,
    }
