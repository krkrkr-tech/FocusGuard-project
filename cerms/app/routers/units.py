"""
CERMS - Response Units router.

Endpoints:
  POST  /units/       – register new response unit
  GET   /units/       – list units (with optional H3 zone filter)
  GET   /units/{id}   – get single unit
  PUT   /units/{id}   – update unit (status, location)
"""

import json
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ResponseUnit, User, AuditLog
from app.schemas import UnitCreate, UnitOut
from app.auth import require_permissions
from app.h3_utils import lat_lng_to_h3

router = APIRouter(prefix="/units", tags=["Response Units"])


@router.post("/", response_model=UnitOut, status_code=201)
def create_unit(
    body: UnitCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("unit.create")),
):
    """Register a new emergency response unit."""
    current_h3 = None
    if body.current_lat is not None and body.current_lng is not None:
        current_h3 = lat_lng_to_h3(body.current_lat, body.current_lng)

    unit = ResponseUnit(
        call_sign=body.call_sign,
        unit_type=body.unit_type.value,
        current_lat=body.current_lat,
        current_lng=body.current_lng,
        current_h3=current_h3,
        assigned_zone_h3=body.assigned_zone_h3,
    )
    db.add(unit)
    db.commit()
    db.refresh(unit)
    return unit


@router.get("/", response_model=List[UnitOut])
def list_units(
    h3_zone: Optional[str] = Query(None, description="Filter by assigned H3 zone"),
    unit_type: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("unit.read")),
):
    q = db.query(ResponseUnit)
    if h3_zone:
        q = q.filter(ResponseUnit.assigned_zone_h3 == h3_zone)
    if unit_type:
        q = q.filter(ResponseUnit.unit_type == unit_type)
    if status_filter:
        q = q.filter(ResponseUnit.status == status_filter)
    return q.all()


@router.get("/{unit_id}", response_model=UnitOut)
def get_unit(
    unit_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("unit.read")),
):
    unit = db.query(ResponseUnit).get(unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    return unit


@router.put("/{unit_id}", response_model=UnitOut)
def update_unit(
    unit_id: int,
    new_status: Optional[str] = Query(None, alias="status"),
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("unit.update")),
):
    """Update unit status and/or GPS location (H3 auto-recomputed)."""
    unit = db.query(ResponseUnit).get(unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")

    if new_status:
        unit.status = new_status
    if lat is not None and lng is not None:
        unit.current_lat = lat
        unit.current_lng = lng
        unit.current_h3 = lat_lng_to_h3(lat, lng)

    db.commit()
    db.refresh(unit)
    return unit
