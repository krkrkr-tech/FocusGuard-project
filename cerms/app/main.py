"""
CERMS - City Emergency Response Management System
Main FastAPI application entry point.
"""

import asyncio
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.database import engine, Base
from app.events import event_consumer

# Import routers
from app.routers.auth_router import router as auth_router
from app.routers.incidents import router as incidents_router
from app.routers.units import router as units_router
from app.routers.dispatch import router as dispatch_router
from app.routers.audit import router as audit_router
from app.routers.zones import zone_router, analytics_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("cerms")


# ──────────── Lifespan: startup + shutdown ────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database ready.")

    # Start the event consumer as a background task
    consumer_task = asyncio.create_task(event_consumer())
    logger.info("Event consumer background task started.")

    yield  # ← application runs here

    # SHUTDOWN
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        pass
    logger.info("CERMS shutdown complete.")


# ──────────── App ────────────

app = FastAPI(
    title="CERMS – City Emergency Response Management System",
    description=(
        "Institutional Information System for coordinating urban emergency "
        "services (police, fire, ambulance) with H3 spatial indexing, RBAC, "
        "event-driven dispatching, and audit logging."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Register routers
app.include_router(auth_router)
app.include_router(incidents_router)
app.include_router(units_router)
app.include_router(dispatch_router)
app.include_router(audit_router)
app.include_router(zone_router)
app.include_router(analytics_router)


@app.get("/", tags=["Root"])
def root():
    return {
        "system": "CERMS – City Emergency Response Management System",
        "version": "1.0.0",
        "docs": "/docs",
        "domain": "Urban Infrastructure – Emergency Response",
    }
