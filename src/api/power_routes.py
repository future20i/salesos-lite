"""PowerMap CRUD routes — B2B decision chain / stakeholder mapping.

Provides:
  - GET /{opportunity_id}         — retrieve power map
  - POST /{opportunity_id}        — create or update (upsert)
  - PATCH /{opportunity_id}/stakeholders  — add/remove/update stakeholders
  - PATCH /{opportunity_id}/connections    — add/remove connections
  - GET /{opportunity_id}/analysis         — LLM-powered decision chain analysis
"""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.auth import get_current_user
from src.models import PowerMap, User

router = APIRouter(prefix="/api/power", tags=["power"])


# ═══════════════════════════════════════════════════════════════════════
#  Pydantic Schemas
# ═══════════════════════════════════════════════════════════════════════

class PowerMapUpsert(BaseModel):
    """Schema for creating or updating a power map."""
    stakeholders: list[dict] | None = None
    connections: list[dict] | None = None
    strategy_notes: str | None = None


class StakeholderAction(BaseModel):
    """Schema for managing stakeholders."""
    action: str  # "add" | "remove" | "update"
    stakeholder: dict  # {person_profile_id, role, stance, concerns, influence_level, notes}


class ConnectionAction(BaseModel):
    """Schema for managing connections."""
    action: str  # "add" | "remove"
    connection: dict  # {from_id, to_id, relationship_type, strength}


class PowerMapResponse(BaseModel):
    """Response schema for a power map."""
    id: str
    opportunity_id: str
    tenant_id: str
    stakeholders: list[dict] | None = None
    connections: list[dict] | None = None
    strategy_notes: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm(cls, obj: PowerMap) -> "PowerMapResponse":
        return cls(
            id=str(obj.id),
            opportunity_id=str(obj.opportunity_id),
            tenant_id=str(obj.tenant_id),
            stakeholders=obj.stakeholders,
            connections=obj.connections,
            strategy_notes=obj.strategy_notes,
            created_at=str(obj.created_at) if obj.created_at else None,
            updated_at=str(obj.updated_at) if obj.updated_at else None,
        )


# ═══════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════

async def _get_power_map(
    opportunity_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> PowerMap | None:
    """Fetch a power map by opportunity_id and tenant_id."""
    stmt = select(PowerMap).where(
        PowerMap.opportunity_id == opportunity_id,
        PowerMap.tenant_id == tenant_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _validate_action(action: str, allowed: set[str], label: str) -> None:
    """Validate that an action string is one of the allowed values."""
    if action not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid {label} action '{action}'. Must be one of: {sorted(allowed)}",
        )


# ═══════════════════════════════════════════════════════════════════════
#  Routes
# ═══════════════════════════════════════════════════════════════════════

@router.get("/{opportunity_id}")
async def get_power_map(
    opportunity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PowerMapResponse:
    """Get the power map for an opportunity.

    Returns 404 if no power map exists for this opportunity.
    Access is granted to any team member with access to the opportunity
    (tenant-scoped through current_user.tenant_id).
    """
    pm = await _get_power_map(opportunity_id, current_user.tenant_id, db)

    if pm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Power map not found for this opportunity",
        )

    return PowerMapResponse.from_orm(pm)


@router.post("/{opportunity_id}")
async def upsert_power_map(
    opportunity_id: uuid.UUID,
    body: PowerMapUpsert,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PowerMapResponse:
    """Create or update the power map for an opportunity.

    If a power map already exists for this opportunity, it is updated.
    Otherwise a new one is created (upsert pattern).
    """
    pm = await _get_power_map(opportunity_id, current_user.tenant_id, db)

    if pm is None:
        # ── Create ──────────────────────────────────────────────────
        pm = PowerMap(
            opportunity_id=opportunity_id,
            tenant_id=current_user.tenant_id,
            stakeholders=body.stakeholders,
            connections=body.connections,
            strategy_notes=body.strategy_notes,
        )
        db.add(pm)
        await db.commit()
        await db.refresh(pm)
    else:
        # ── Update ──────────────────────────────────────────────────
        if body.stakeholders is not None:
            pm.stakeholders = body.stakeholders
        if body.connections is not None:
            pm.connections = body.connections
        if body.strategy_notes is not None:
            pm.strategy_notes = body.strategy_notes
        await db.commit()
        await db.refresh(pm)

    return PowerMapResponse.from_orm(pm)


@router.patch("/{opportunity_id}/stakeholders")
async def manage_stakeholders(
    opportunity_id: uuid.UUID,
    body: StakeholderAction,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PowerMapResponse:
    """Add, remove, or update a stakeholder in the power map.

    - **add**: appends the stakeholder to the stakeholders array
    - **remove**: removes the stakeholder matching person_profile_id
    - **update**: finds by person_profile_id and updates fields

    Returns the updated power map.
    """
    _validate_action(body.action, {"add", "remove", "update"}, "stakeholder")

    pm = await _get_power_map(opportunity_id, current_user.tenant_id, db)
    if pm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Power map not found for this opportunity",
        )

    stakeholders: list[dict] = list(pm.stakeholders) if pm.stakeholders else []
    person_id = body.stakeholder.get("person_profile_id")

    if body.action == "add":
        if person_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="stakeholder.person_profile_id is required for add",
            )
        stakeholders.append(body.stakeholder)

    elif body.action == "remove":
        if person_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="stakeholder.person_profile_id is required for remove",
            )
        stakeholders = [s for s in stakeholders if s.get("person_profile_id") != person_id]

    elif body.action == "update":
        if person_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="stakeholder.person_profile_id is required for update",
            )
        updated = False
        for i, s in enumerate(stakeholders):
            if s.get("person_profile_id") == person_id:
                stakeholders[i] = {**s, **body.stakeholder}
                updated = True
                break
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Stakeholder with person_profile_id '{person_id}' not found",
            )

    pm.stakeholders = stakeholders
    await db.commit()
    await db.refresh(pm)

    return PowerMapResponse.from_orm(pm)


@router.patch("/{opportunity_id}/connections")
async def manage_connections(
    opportunity_id: uuid.UUID,
    body: ConnectionAction,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PowerMapResponse:
    """Add or remove a connection in the power map.

    - **add**: appends the connection to the connections array
    - **remove**: removes all connections matching both from_id and to_id

    Returns the updated power map.
    """
    _validate_action(body.action, {"add", "remove"}, "connection")

    pm = await _get_power_map(opportunity_id, current_user.tenant_id, db)
    if pm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Power map not found for this opportunity",
        )

    connections: list[dict] = list(pm.connections) if pm.connections else []
    from_id = body.connection.get("from_id")
    to_id = body.connection.get("to_id")

    if body.action == "add":
        if from_id is None or to_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="connection.from_id and connection.to_id are required for add",
            )
        connections.append(body.connection)

    elif body.action == "remove":
        if from_id is None or to_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="connection.from_id and connection.to_id are required for remove",
            )
        connections = [
            c
            for c in connections
            if not (c.get("from_id") == from_id and c.get("to_id") == to_id)
        ]

    pm.connections = connections
    await db.commit()
    await db.refresh(pm)

    return PowerMapResponse.from_orm(pm)


@router.get("/{opportunity_id}/analysis")
async def power_map_analysis(
    opportunity_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate a decision chain analysis using LLM.

    Returns:
    - coverage_score (0-100): how well covered the decision chain is
    - gaps: list of missing roles or uncovered stakeholders
    - risk_zones: stakeholders with stance "opponent" or high risk
    - recommended_actions: suggested next steps

    Falls back to a basic heuristic analysis if the LLM is unavailable.
    """
    pm = await _get_power_map(opportunity_id, current_user.tenant_id, db)
    if pm is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Power map not found for this opportunity",
        )

    stakeholders = pm.stakeholders or []
    strategy_notes = pm.strategy_notes or ""

    # ── Build prompt for LLM ────────────────────────────────────────
    stakeholders_json = json.dumps(stakeholders, ensure_ascii=False, indent=2)

    prompt = f"""Analyze the following B2B sales power map stakeholders and strategy notes. 
Return a JSON object with these keys:

- coverage_score: integer 0-100, how well covered the decision chain is
- gaps: array of strings describing missing roles or uncovered areas
- risk_zones: array of strings describing stakeholders who are opponents or high risk
- recommended_actions: array of strings with concrete next steps to improve position

Stakeholders:
{stakeholders_json}

Strategy notes:
{strategy_notes if strategy_notes else "(none)"}

Respond ONLY with valid JSON. No markdown, no explanation."""

    # ── Call LLM ────────────────────────────────────────────────────
    from src.llm_client import llm_complete

    llm_response = await llm_complete(
        prompt=prompt,
        system="You are a B2B sales strategist. Respond with JSON only. Be concise and actionable.",
    )

    # ── Try to parse LLM JSON; fall back to heuristics ──────────────
    try:
        result = json.loads(llm_response)
        return {
            "coverage_score": int(result.get("coverage_score", 0)),
            "gaps": result.get("gaps", []),
            "risk_zones": result.get("risk_zones", []),
            "recommended_actions": result.get("recommended_actions", []),
        }
    except (json.JSONDecodeError, ValueError):
        # ── Heuristic fallback ──────────────────────────────────────
        roles_present = {s.get("role") for s in stakeholders if s.get("role")}
        all_roles = {"decision_maker", "influencer", "gatekeeper", "user", "coach"}
        missing_roles = all_roles - roles_present

        opponents = [s for s in stakeholders if s.get("stance") == "opponent"]
        champions = [s for s in stakeholders if s.get("stance") == "champion"]

        # Simple coverage heuristic
        if not stakeholders:
            coverage_score = 0
        else:
            coverage_score = max(0, 100 - len(missing_roles) * 20 - len(opponents) * 15)

        gaps = [f"Missing role: {r}" for r in sorted(missing_roles)]
        risk_zones = [
            f"{o.get('person_profile_id','?')}: {o.get('concerns','opponent stance')}"
            for o in opponents
        ]
        recommended_actions = []
        if missing_roles:
            recommended_actions.append(f"Identify and map stakeholders for: {', '.join(sorted(missing_roles))}")
        if opponents:
            recommended_actions.append(
                f"Develop influence strategy to convert {len(opponents)} opponent(s) — "
                "leverage existing champions or find their concerns"
            )
        if not champions:
            recommended_actions.append("Identify and cultivate at least one internal champion")
        if not recommended_actions:
            recommended_actions.append("Maintain engagement with current stakeholders")

        return {
            "coverage_score": coverage_score,
            "gaps": gaps,
            "risk_zones": risk_zones,
            "recommended_actions": recommended_actions,
        }
