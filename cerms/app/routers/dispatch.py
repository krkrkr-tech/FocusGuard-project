import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    DispatchEvent, DispatchEventType,
    Incident, IncidentStatus,
    ResponseUnit, UnitStatus,
    User, AuditLog,
)
from app.schemas import DispatchRequest, DispatchEventOut
from app.auth import require_permissions
from app.events import publish_event

router = APIRouter(prefix="/dispatch", tags=["Dispatch (Event-Driven)"])


@router.post("/", response_model=DispatchEventOut, status_code=201)
async def create_dispatch(
    body: DispatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("dispatch.create")),
):
    incident = db.query(Incident).get(body.incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    unit = db.query(ResponseUnit).get(body.unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    if unit.status != UnitStatus.AVAILABLE:
        raise HTTPException(status_code=409, detail=f"Unit {unit.call_sign} is not available (status={unit.status.value})")

    dispatch_ev = DispatchEvent(
        incident_id=body.incident_id,
        unit_id=body.unit_id,
        event_type=DispatchEventType.DISPATCHED,
        notes=body.notes,
    )
    db.add(dispatch_ev)
    db.flush()

    audit = AuditLog(
        user_id=user.id,
        username=user.username,
        action="dispatch.create",
        resource_type="dispatch",
        resource_id=dispatch_ev.id,
        details=json.dumps({
            "incident_id": body.incident_id,
            "unit_id": body.unit_id,
            "unit_call_sign": unit.call_sign,
        }),
    )
    db.add(audit)
    db.commit()
    db.refresh(dispatch_ev)

    await publish_event({
        "event_type": "dispatch.created",
        "dispatch_event_id": dispatch_ev.id,
        "incident_id": body.incident_id,
        "unit_id": body.unit_id,
        "dispatcher_id": user.id,
        "dispatcher_username": user.username,
    })

    return dispatch_ev


@router.get("/", response_model=List[DispatchEventOut])
def list_dispatches(
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("dispatch.read")),
):
    return db.query(DispatchEvent).order_by(DispatchEvent.timestamp.desc()).all()


@router.post("/resolve", response_model=DispatchEventOut, status_code=201)
async def resolve_dispatch(
    body: DispatchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("dispatch.create")),
):
    incident = db.query(Incident).get(body.incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")

    incident.status = IncidentStatus.RESOLVED

    dispatch_ev = DispatchEvent(
        incident_id=body.incident_id,
        unit_id=body.unit_id,
        event_type=DispatchEventType.RESOLVED,
        notes=body.notes,
    )
    db.add(dispatch_ev)
    db.commit()
    db.refresh(dispatch_ev)

    await publish_event({
        "event_type": "dispatch.resolved",
        "dispatch_event_id": dispatch_ev.id,
        "incident_id": body.incident_id,
        "unit_id": body.unit_id,
    })

    return dispatch_ev
