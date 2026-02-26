import json
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Zone, Incident, DispatchEvent, ZoneAnalytics,
    User, IncidentSeverity, DispatchEventType,
)
from app.schemas import ZoneCreate, ZoneOut, ZoneAnalyticsOut
from app.auth import require_permissions
from app.h3_utils import h3_resolution_info, is_valid_h3

zone_router = APIRouter(prefix="/zones", tags=["Zones (H3)"])
analytics_router = APIRouter(prefix="/analytics", tags=["Analytics"])


@zone_router.post("/", response_model=ZoneOut, status_code=201)
def create_zone(
    body: ZoneCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("zone.create")),
):
    if not is_valid_h3(body.h3_index):
        raise HTTPException(status_code=400, detail="Invalid H3 index")
    zone = Zone(**body.model_dump())
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return zone


@zone_router.get("/", response_model=List[ZoneOut])
def list_zones(
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("zone.read")),
):
    return db.query(Zone).all()


@zone_router.get("/h3-info")
def get_h3_info(user: User = Depends(require_permissions("zone.read"))):
    return h3_resolution_info()


@analytics_router.get("/", response_model=List[ZoneAnalyticsOut])
def list_analytics(
    h3_index: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("analytics.read")),
):
    q = db.query(ZoneAnalytics)
    if h3_index:
        q = q.filter(ZoneAnalytics.h3_index == h3_index)
    return q.order_by(ZoneAnalytics.period_start.desc()).all()


@analytics_router.post("/refresh")
def refresh_analytics(
    db: Session = Depends(get_db),
    user: User = Depends(require_permissions("analytics.read")),
):
    now = datetime.now(timezone.utc)
    period_start = now - timedelta(days=30)

    h3_zones = (
        db.query(Incident.h3_index)
        .filter(Incident.created_at >= period_start)
        .distinct()
        .all()
    )

    results = []
    for (h3_idx,) in h3_zones:
        total = db.query(func.count(Incident.id)).filter(
            Incident.h3_index == h3_idx,
            Incident.created_at >= period_start,
        ).scalar()

        critical = db.query(func.count(Incident.id)).filter(
            Incident.h3_index == h3_idx,
            Incident.severity == IncidentSeverity.CRITICAL,
            Incident.created_at >= period_start,
        ).scalar()

        dispatches = (
            db.query(func.count(DispatchEvent.id))
            .join(Incident, Incident.id == DispatchEvent.incident_id)
            .filter(
                Incident.h3_index == h3_idx,
                DispatchEvent.event_type == DispatchEventType.DISPATCHED,
                DispatchEvent.timestamp >= period_start,
            )
            .scalar()
        )

        resolved = (
            db.query(func.count(DispatchEvent.id))
            .join(Incident, Incident.id == DispatchEvent.incident_id)
            .filter(
                Incident.h3_index == h3_idx,
                DispatchEvent.event_type == DispatchEventType.RESOLVED,
                DispatchEvent.timestamp >= period_start,
            )
            .scalar()
        )

        existing = db.query(ZoneAnalytics).filter(
            ZoneAnalytics.h3_index == h3_idx,
            ZoneAnalytics.period_start == period_start,
        ).first()

        if existing:
            existing.total_incidents = total
            existing.critical_incidents = critical
            existing.dispatches = dispatches
            existing.resolved = resolved
        else:
            za = ZoneAnalytics(
                h3_index=h3_idx,
                period_start=period_start,
                period_end=now,
                total_incidents=total,
                critical_incidents=critical,
                avg_response_minutes=0.0,
                dispatches=dispatches,
                resolved=resolved,
            )
            db.add(za)

        results.append({
            "h3_index": h3_idx,
            "total_incidents": total,
            "critical": critical,
            "dispatches": dispatches,
            "resolved": resolved,
        })

    db.commit()
    return {"status": "refreshed", "zones_processed": len(results), "data": results}
