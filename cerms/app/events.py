"""
CERMS - Event-driven dispatch simulation.

Uses a simple in-process asyncio queue to simulate an event bus.
When a dispatch is created, an event is placed on the queue.
A background consumer processes dispatch events asynchronously
(e.g., updating unit status, logging).
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import (
    DispatchEvent, DispatchEventType,
    ResponseUnit, UnitStatus,
    Incident, IncidentStatus,
    AuditLog,
)

logger = logging.getLogger("cerms.events")

# ──────────── In-memory async event queue ────────────
event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)


async def publish_event(event_data: dict):
    """Place an event on the queue for async processing."""
    await event_queue.put(event_data)
    logger.info(f"Event published: {event_data.get('event_type')}")


async def event_consumer():
    """
    Background task that continuously processes dispatch events.
    This simulates an event-driven architecture component.
    """
    logger.info("Event consumer started — listening for dispatch events...")
    while True:
        try:
            event_data = await asyncio.wait_for(event_queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            logger.info("Event consumer shutting down.")
            break

        try:
            await _handle_event(event_data)
        except Exception as exc:
            logger.error(f"Error handling event: {exc}")
        finally:
            event_queue.task_done()


async def _handle_event(event_data: dict):
    """Process a single dispatch event."""
    event_type = event_data.get("event_type")
    db: Session = SessionLocal()
    try:
        if event_type == "dispatch.created":
            unit_id = event_data["unit_id"]
            incident_id = event_data["incident_id"]

            # Update unit status → DISPATCHED
            unit = db.query(ResponseUnit).get(unit_id)
            if unit:
                unit.status = UnitStatus.DISPATCHED
                db.commit()
                logger.info(f"Unit {unit.call_sign} status → DISPATCHED")

            # Update incident status → DISPATCHED
            incident = db.query(Incident).get(incident_id)
            if incident and incident.status == IncidentStatus.REPORTED:
                incident.status = IncidentStatus.DISPATCHED
                db.commit()
                logger.info(f"Incident #{incident.id} status → DISPATCHED")

            # Audit log
            audit = AuditLog(
                user_id=event_data.get("dispatcher_id"),
                username=event_data.get("dispatcher_username"),
                action="dispatch.event_processed",
                resource_type="dispatch",
                resource_id=event_data.get("dispatch_event_id"),
                details=json.dumps({
                    "unit_id": unit_id,
                    "incident_id": incident_id,
                    "event": "auto-processed by event consumer",
                }),
            )
            db.add(audit)
            db.commit()

        elif event_type == "dispatch.resolved":
            unit_id = event_data["unit_id"]
            unit = db.query(ResponseUnit).get(unit_id)
            if unit:
                unit.status = UnitStatus.AVAILABLE
                db.commit()
                logger.info(f"Unit {unit.call_sign} status → AVAILABLE (resolved)")

        else:
            logger.warning(f"Unknown event type: {event_type}")

    finally:
        db.close()
