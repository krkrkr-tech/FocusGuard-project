"""
CERMS - Incidents router.

Endpoints:
  POST   /incidents/           – create incident
  GET    /incidents/           – list incidents (with optional h3 filter)
  GET    /incidents/{id}       – get single incident
  PUT    /incidents/{id}       – update incident
  POST   /incidents/h3-query   – query incidents by H3 index + k-ring (spatial query)
"""

import json
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Incident, User, AuditLog, RoleEnum
from app.schemas import IncidentCreate, IncidentUpdate, IncidentOut, H3NeighborQuery
from app.auth import require_permissions, get_current_user
from app.h3_utils import lat_lng_to_h3, get_k_ring

router = APIRouter(prefix="/incidents", tags=["Incidents"])


# ──────── ABAC helper ────────

def _abac_filter(user: User, incident: Incident):
    """
    ABAC Rule: A responder can only access incidents in their assigned zone
    or the zone's k=1 neighbors. Admins/dispatchers bypass.
    """
    if user.role in (RoleEnum.ADMIN, RoleEnum.DISPATCHER, RoleEnum.ANALYST, RoleEnum.AUDITOR):
        return  # full access
    if user.role == RoleEnum.RESPONDER:
        if not user.assigned_zone_h3:
            raise HTTPException(status_code=403, detail="Responder has no assigned zone")
        allowed_zones = get_k_ring(user.assigned_zone_h3, k=1)
        if incident.h3_index not in allowed_zones:
            raise HTTPException(
                status_code=403,
                detail="ABAC: incident is outside your assigned zone",
            )


# ──────── Endpoints ────────

@router.post("/", response_model=IncidentOut, status_code=201)
def create_incident(
    body: IncidentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("incident.create")),
):
    """Report a new emergency incident. H3 index auto-computed from lat/lng."""
    h3_index = lat_lng_to_h3(body.latitude, body.longitude)

    incident = Incident(
        title=body.title,
        description=body.description,
        severity=body.severity.value,
        reported_by=user.id,
        latitude=body.latitude,
        longitude=body.longitude,
        h3_index=h3_index,
    )
    db.add(incident)
    db.flush()

    # Audit: incident created
    audit = AuditLog(
        user_id=user.id,
        username=user.username,
        action="incident.create",
        resource_type="incident",
        resource_id=incident.id,
        details=json.dumps({"title": body.title, "severity": body.severity.value, "h3": h3_index}),
    )
    db.add(audit)
    db.commit()
    db.refresh(incident)
    return incident


@router.get("/", response_model=List[IncidentOut])
def list_incidents(
    h3_index: Optional[str] = Query(None, description="Filter by H3 zone"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("incident.read")),
):
    """List incidents, optionally filtered by H3 zone and/or status."""
    q = db.query(Incident)

    # ABAC: responders see only their zone
    if user.role == RoleEnum.RESPONDER and user.assigned_zone_h3:
        allowed = get_k_ring(user.assigned_zone_h3, k=1)
        q = q.filter(Incident.h3_index.in_(allowed))

    if h3_index:
        q = q.filter(Incident.h3_index == h3_index)
    if status_filter:
        q = q.filter(Incident.status == status_filter)

    return q.order_by(Incident.created_at.desc()).limit(limit).all()


@router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("incident.read")),
):
    incident = db.query(Incident).get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    _abac_filter(user, incident)
    return incident


@router.put("/{incident_id}", response_model=IncidentOut)
def update_incident(
    incident_id: int,
    body: IncidentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("incident.update")),
):
    incident = db.query(Incident).get(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    _abac_filter(user, incident)

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(incident, key, value.value if hasattr(value, "value") else value)

    db.commit()
    db.refresh(incident)
    return incident


@router.post("/h3-query", response_model=List[IncidentOut])
def query_incidents_by_h3(
    body: H3NeighborQuery,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("incident.read")),
):
    """
    Spatial query: return all incidents within the given H3 cell
    and its k-ring neighbors.
    """
    h3_cells = list(get_k_ring(body.h3_index, body.k_ring))
    results = (
        db.query(Incident)
        .filter(Incident.h3_index.in_(h3_cells))
        .order_by(Incident.created_at.desc())
        .all()
    )
    return results
