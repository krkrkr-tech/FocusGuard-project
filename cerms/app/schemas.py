"""
CERMS - Pydantic request / response schemas.
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from app.models import (
    RoleEnum, IncidentSeverity, IncidentStatus,
    UnitType, UnitStatus, DispatchEventType,
)


# ───────── Auth ─────────

class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: RoleEnum
    is_active: bool
    assigned_zone_h3: Optional[str] = None

    class Config:
        from_attributes = True


# ───────── Incidents ─────────

class IncidentCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = None
    severity: IncidentSeverity
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class IncidentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[IncidentSeverity] = None
    status: Optional[IncidentStatus] = None


class IncidentOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    severity: IncidentSeverity
    status: IncidentStatus
    reported_by: int
    latitude: float
    longitude: float
    h3_index: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ───────── Response Units ─────────

class UnitCreate(BaseModel):
    call_sign: str = Field(..., max_length=30)
    unit_type: UnitType
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None
    assigned_zone_h3: Optional[str] = None


class UnitOut(BaseModel):
    id: int
    call_sign: str
    unit_type: UnitType
    status: UnitStatus
    current_lat: Optional[float]
    current_lng: Optional[float]
    current_h3: Optional[str]
    assigned_zone_h3: Optional[str]

    class Config:
        from_attributes = True


# ───────── Dispatch ─────────

class DispatchRequest(BaseModel):
    incident_id: int
    unit_id: int
    notes: Optional[str] = None


class DispatchEventOut(BaseModel):
    id: int
    incident_id: int
    unit_id: int
    event_type: DispatchEventType
    timestamp: datetime
    notes: Optional[str]

    class Config:
        from_attributes = True


# ───────── Zones ─────────

class ZoneCreate(BaseModel):
    h3_index: str
    name: str
    city: str = "Astana"
    risk_level: str = "normal"


class ZoneOut(BaseModel):
    id: int
    h3_index: str
    name: str
    city: str
    risk_level: str

    class Config:
        from_attributes = True


# ───────── Audit ─────────

class AuditLogOut(BaseModel):
    id: int
    timestamp: datetime
    user_id: Optional[int]
    username: Optional[str]
    action: str
    resource_type: Optional[str]
    resource_id: Optional[int]
    details: Optional[str]
    ip_address: Optional[str]

    class Config:
        from_attributes = True


# ───────── Analytics ─────────

class ZoneAnalyticsOut(BaseModel):
    id: int
    h3_index: str
    period_start: datetime
    period_end: datetime
    total_incidents: int
    critical_incidents: int
    avg_response_minutes: float
    dispatches: int
    resolved: int

    class Config:
        from_attributes = True


class H3NeighborQuery(BaseModel):
    """Query incidents within an H3 hex and its k-ring neighbors."""
    h3_index: str
    k_ring: int = Field(default=1, ge=0, le=5)
