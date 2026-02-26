"""
CERMS - SQLAlchemy ORM Models

Tables:
  users           – system users (dispatchers, responders, analysts, admins, auditors)
  zones           – H3-indexed geographic zones with assigned jurisdiction
  response_units  – vehicles / teams (police car, ambulance, fire truck)
  incidents       – emergency incidents with H3 spatial index
  dispatch_events – event-driven dispatch log (unit → incident assignment)
  audit_log       – immutable audit trail for sensitive actions
  zone_analytics  – pre-aggregated analytics per H3 zone (materialized view style)
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean,
    ForeignKey, Text, Enum as SAEnum, Index
)
from sqlalchemy.orm import relationship
from app.database import Base
import enum


# ──────────────────────────── Enums ────────────────────────────

class RoleEnum(str, enum.Enum):
    ADMIN = "admin"
    DISPATCHER = "dispatcher"
    RESPONDER = "responder"
    ANALYST = "analyst"
    AUDITOR = "auditor"


class IncidentSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, enum.Enum):
    REPORTED = "reported"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class UnitType(str, enum.Enum):
    POLICE = "police"
    FIRE = "fire"
    AMBULANCE = "ambulance"


class UnitStatus(str, enum.Enum):
    AVAILABLE = "available"
    DISPATCHED = "dispatched"
    ON_SCENE = "on_scene"
    RETURNING = "returning"
    OFF_DUTY = "off_duty"


class DispatchEventType(str, enum.Enum):
    DISPATCHED = "dispatched"
    ARRIVED = "arrived"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


# ──────────────────────────── Models ────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(120), nullable=False)
    role = Column(SAEnum(RoleEnum), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # A responder may be linked to a zone (ABAC: can only see incidents in their zone)
    assigned_zone_h3 = Column(String(20), nullable=True)


class Zone(Base):
    """Geographic zone defined by H3 index."""
    __tablename__ = "zones"

    id = Column(Integer, primary_key=True, index=True)
    h3_index = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    city = Column(String(80), nullable=False, default="Astana")
    risk_level = Column(String(20), default="normal")  # normal, elevated, high
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ResponseUnit(Base):
    """Emergency response unit (vehicle/team)."""
    __tablename__ = "response_units"

    id = Column(Integer, primary_key=True, index=True)
    call_sign = Column(String(30), unique=True, nullable=False)
    unit_type = Column(SAEnum(UnitType), nullable=False)
    status = Column(SAEnum(UnitStatus), default=UnitStatus.AVAILABLE)
    current_lat = Column(Float, nullable=True)
    current_lng = Column(Float, nullable=True)
    current_h3 = Column(String(20), nullable=True, index=True)
    assigned_zone_h3 = Column(String(20), nullable=True)

    dispatch_events = relationship("DispatchEvent", back_populates="unit")


class Incident(Base):
    """Emergency incident report."""
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(SAEnum(IncidentSeverity), nullable=False)
    status = Column(SAEnum(IncidentStatus), default=IncidentStatus.REPORTED)
    reported_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    h3_index = Column(String(20), nullable=False, index=True)  # ← H3 spatial index
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    reporter = relationship("User", foreign_keys=[reported_by])
    dispatch_events = relationship("DispatchEvent", back_populates="incident")

    __table_args__ = (
        Index("ix_incidents_h3_status", "h3_index", "status"),
    )


class DispatchEvent(Base):
    """Event-driven dispatch record — links a unit to an incident."""
    __tablename__ = "dispatch_events"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False)
    unit_id = Column(Integer, ForeignKey("response_units.id"), nullable=False)
    event_type = Column(SAEnum(DispatchEventType), nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    notes = Column(Text, nullable=True)

    incident = relationship("Incident", back_populates="dispatch_events")
    unit = relationship("ResponseUnit", back_populates="dispatch_events")


class AuditLog(Base):
    """Immutable audit trail — records sensitive actions."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(50), nullable=True)
    action = Column(String(100), nullable=False)     # e.g. "incident.create", "dispatch.assign"
    resource_type = Column(String(50), nullable=True) # e.g. "incident", "unit"
    resource_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)             # JSON or free-text
    ip_address = Column(String(45), nullable=True)


class ZoneAnalytics(Base):
    """Pre-aggregated analytics per H3 zone (updated periodically or on-demand)."""
    __tablename__ = "zone_analytics"

    id = Column(Integer, primary_key=True, index=True)
    h3_index = Column(String(20), nullable=False, index=True)
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    total_incidents = Column(Integer, default=0)
    critical_incidents = Column(Integer, default=0)
    avg_response_minutes = Column(Float, default=0.0)
    dispatches = Column(Integer, default=0)
    resolved = Column(Integer, default=0)

    __table_args__ = (
        Index("ix_zone_analytics_h3_period", "h3_index", "period_start"),
    )
