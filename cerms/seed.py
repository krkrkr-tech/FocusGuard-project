"""
CERMS - Database seed script.

Run:  python -m seed
from the cerms/ directory.

Creates sample users, zones, response units, and incidents
for demonstration purposes.
"""

import sys
import os

# Ensure app package is importable
sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine, SessionLocal, Base
from app.models import (
    User, Zone, ResponseUnit, Incident,
    RoleEnum, UnitType, UnitStatus, IncidentSeverity, IncidentStatus,
)
from app.auth import hash_password
from app.h3_utils import lat_lng_to_h3

def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # ─── Check if already seeded ───
    if db.query(User).first():
        print("Database already seeded. Skipping.")
        db.close()
        return

    print("Seeding database...")

    # ═══════════════ USERS ═══════════════
    # Astana city center H3 (≈ 51.1694, 71.4491)
    astana_center_h3 = lat_lng_to_h3(51.1694, 71.4491)
    astana_south_h3 = lat_lng_to_h3(51.1000, 71.4300)
    astana_north_h3 = lat_lng_to_h3(51.2000, 71.4700)

    users = [
        User(username="admin", hashed_password=hash_password("admin123"),
             full_name="System Administrator", role=RoleEnum.ADMIN),
        User(username="dispatcher1", hashed_password=hash_password("disp123"),
             full_name="Aisha Nurzhanova", role=RoleEnum.DISPATCHER),
        User(username="responder1", hashed_password=hash_password("resp123"),
             full_name="Marat Bekturov", role=RoleEnum.RESPONDER,
             assigned_zone_h3=astana_center_h3),
        User(username="responder2", hashed_password=hash_password("resp123"),
             full_name="Dinara Kairatova", role=RoleEnum.RESPONDER,
             assigned_zone_h3=astana_south_h3),
        User(username="analyst1", hashed_password=hash_password("analyst123"),
             full_name="Yerlan Ospanov", role=RoleEnum.ANALYST),
        User(username="auditor1", hashed_password=hash_password("audit123"),
             full_name="Gulnara Iskakova", role=RoleEnum.AUDITOR),
    ]
    db.add_all(users)
    db.flush()
    print(f"  Created {len(users)} users")

    # ═══════════════ ZONES ═══════════════
    zones = [
        Zone(h3_index=astana_center_h3, name="Astana City Center",
             city="Astana", risk_level="elevated"),
        Zone(h3_index=astana_south_h3, name="Astana South District",
             city="Astana", risk_level="normal"),
        Zone(h3_index=astana_north_h3, name="Astana North District",
             city="Astana", risk_level="normal"),
    ]
    db.add_all(zones)
    db.flush()
    print(f"  Created {len(zones)} zones")

    # ═══════════════ RESPONSE UNITS ═══════════════
    units = [
        ResponseUnit(call_sign="POLICE-01", unit_type=UnitType.POLICE,
                     status=UnitStatus.AVAILABLE,
                     current_lat=51.1700, current_lng=71.4500,
                     current_h3=lat_lng_to_h3(51.1700, 71.4500),
                     assigned_zone_h3=astana_center_h3),
        ResponseUnit(call_sign="FIRE-01", unit_type=UnitType.FIRE,
                     status=UnitStatus.AVAILABLE,
                     current_lat=51.1050, current_lng=71.4350,
                     current_h3=lat_lng_to_h3(51.1050, 71.4350),
                     assigned_zone_h3=astana_south_h3),
        ResponseUnit(call_sign="AMB-01", unit_type=UnitType.AMBULANCE,
                     status=UnitStatus.AVAILABLE,
                     current_lat=51.1680, current_lng=71.4480,
                     current_h3=lat_lng_to_h3(51.1680, 71.4480),
                     assigned_zone_h3=astana_center_h3),
        ResponseUnit(call_sign="POLICE-02", unit_type=UnitType.POLICE,
                     status=UnitStatus.AVAILABLE,
                     current_lat=51.2010, current_lng=71.4710,
                     current_h3=lat_lng_to_h3(51.2010, 71.4710),
                     assigned_zone_h3=astana_north_h3),
        ResponseUnit(call_sign="AMB-02", unit_type=UnitType.AMBULANCE,
                     status=UnitStatus.OFF_DUTY,
                     current_lat=51.1100, current_lng=71.4200,
                     current_h3=lat_lng_to_h3(51.1100, 71.4200),
                     assigned_zone_h3=astana_south_h3),
    ]
    db.add_all(units)
    db.flush()
    print(f"  Created {len(units)} response units")

    # ═══════════════ INCIDENTS ═══════════════
    dispatcher = db.query(User).filter(User.username == "dispatcher1").first()
    incidents = [
        Incident(
            title="Traffic accident on Kabanbay Batyr Ave",
            description="Multi-vehicle collision, injuries reported.",
            severity=IncidentSeverity.HIGH,
            status=IncidentStatus.REPORTED,
            reported_by=dispatcher.id,
            latitude=51.1694, longitude=71.4491,
            h3_index=lat_lng_to_h3(51.1694, 71.4491),
        ),
        Incident(
            title="Building fire at Turan Street",
            description="Smoke visible from residential building, 3rd floor.",
            severity=IncidentSeverity.CRITICAL,
            status=IncidentStatus.REPORTED,
            reported_by=dispatcher.id,
            latitude=51.1020, longitude=71.4310,
            h3_index=lat_lng_to_h3(51.1020, 71.4310),
        ),
        Incident(
            title="Medical emergency at Mega Silk Way",
            description="Elderly person collapsed in shopping center.",
            severity=IncidentSeverity.MEDIUM,
            status=IncidentStatus.REPORTED,
            reported_by=dispatcher.id,
            latitude=51.0900, longitude=71.4100,
            h3_index=lat_lng_to_h3(51.0900, 71.4100),
        ),
        Incident(
            title="Suspicious package at railway station",
            description="Unattended bag reported by security.",
            severity=IncidentSeverity.HIGH,
            status=IncidentStatus.REPORTED,
            reported_by=dispatcher.id,
            latitude=51.1720, longitude=71.4530,
            h3_index=lat_lng_to_h3(51.1720, 71.4530),
        ),
        Incident(
            title="Water main break on Respublika Ave",
            description="Flooding on road, traffic blocked.",
            severity=IncidentSeverity.LOW,
            status=IncidentStatus.REPORTED,
            reported_by=dispatcher.id,
            latitude=51.2050, longitude=71.4680,
            h3_index=lat_lng_to_h3(51.2050, 71.4680),
        ),
    ]
    db.add_all(incidents)
    db.flush()
    print(f"  Created {len(incidents)} incidents")

    db.commit()
    db.close()
    print("Seed complete!")


if __name__ == "__main__":
    seed()
