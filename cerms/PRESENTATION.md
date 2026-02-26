# CERMS – City Emergency Response Management System
## Phase 2 Presentation

---

## 1. System Framing

### Institutional Problem
Astana's emergency services (police, fire, ambulance) operate across a sprawling urban area. Without a centralized coordination system, dispatchers cannot efficiently assign the nearest available unit to reported incidents. Critical data (incident reports, dispatch history, personnel locations) lives in siloed paper logs or incompatible systems, leading to delayed response times and accountability gaps.

**CERMS** provides a unified digital backbone for incident reporting, zone-based dispatching, real-time unit tracking, and auditable decision trails.

### Stakeholder Table

| Stakeholder               | Role                         | Power     | Risk                                         |
|---------------------------|------------------------------|-----------|----------------------------------------------|
| City Emergency Commission | Governance & policy          | High      | Policy failure → system misalignment         |
| Dispatch Center Operators | Create incidents, dispatch   | High      | Wrong dispatch → delayed response            |
| Field Responders          | Execute on-ground response   | Medium    | Receive incorrect/outdated information        |
| Data Analysts             | Trends, resource planning    | Medium    | Flawed analytics → poor resource allocation  |
| IT Administration         | System ops, access control   | High      | Misconfiguration → security breach           |
| Audit / Compliance Office | Oversight, legal compliance  | Medium    | Missing logs → legal liability               |
| Citizens                  | Report emergencies           | Low       | Slow response → loss of life/property        |

### System Boundaries
- **In scope**: Incident lifecycle, unit dispatch, H3-based zoning, RBAC, audit trail, analytics.
- **Out of scope**: 911 call routing, real-time GPS hardware integration, citizen-facing mobile app, AI-based routing.

### Critical Failure Scenario
> A dispatcher accidentally assigns a fire unit to a medical emergency in a neighboring zone while the local ambulance sits idle. The system must prevent this by showing zone-filtered available units and logging every dispatch decision. If the event queue fails, the dispatch record still exists in the DB — the async status update simply runs on the next retry.

---

## 2. Architecture Overview

### Architecture: Monolith with Event-Driven Component

```
┌──────────────────────────────────────────────────────┐
│                    FastAPI Monolith                   │
│                                                      │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐           │
│  │  Auth   │  │ Incidents│  │  Units   │           │
│  │ Router  │  │  Router  │  │  Router  │           │
│  └────┬────┘  └────┬─────┘  └────┬─────┘           │
│       │            │             │                   │
│  ┌────┴────┐  ┌────┴─────┐  ┌───┴──────┐           │
│  │Dispatch │  │  Zones/  │  │  Audit   │           │
│  │ Router  │  │Analytics │  │  Router  │           │
│  └────┬────┘  └────┬─────┘  └──────────┘           │
│       │            │                                 │
│       ▼            ▼                                 │
│  ┌─────────────────────────┐                        │
│  │   SQLAlchemy ORM Layer  │◄── H3 Utils            │
│  └───────────┬─────────────┘                        │
│              │                                       │
│  ┌───────────▼─────────────┐  ┌──────────────────┐  │
│  │    SQLite Database      │  │  Async Event     │  │
│  │  (7 tables + indexes)   │  │  Queue + Consumer│  │
│  └─────────────────────────┘  └──────────────────┘  │
└──────────────────────────────────────────────────────┘
```

### Justification
- **Monolith** chosen because this is a single-team, city-scale system. Microservices would add deployment complexity without proportional benefit. The domain is cohesive (incident → dispatch → resolve).
- **Event-driven component**: The dispatch flow publishes events to an async in-process queue. A background consumer updates unit/incident statuses asynchronously — simulating a real message broker (RabbitMQ / Kafka). This decouples the "record the dispatch" step from "propagate state changes."
- **Failure handling**: If the event consumer crashes, the dispatch DB record is already committed. A startup reconciliation query or retry mechanism can reprocess unfinished events.

### Where H3 is Used
1. **Incident table** — `h3_index` column auto-computed from lat/lng at creation.
2. **Response units** — `current_h3` tracks real-time zone; `assigned_zone_h3` defines home zone.
3. **Zones table** — H3 index is the primary geographic key.
4. **Spatial queries** — `POST /incidents/h3-query` uses `k_ring()` for neighbor lookup.
5. **ABAC** — Responder access is restricted to their zone's H3 k=1 ring.
6. **Analytics** — Aggregation per H3 zone (incident count, severity breakdown, response stats).

---

## 3. Data Modeling

### ER Diagram (Conceptual)

```
┌──────────┐     ┌────────────┐     ┌───────────────┐
│   User   │────<│  Incident  │>────│ DispatchEvent │
│          │     │            │     │               │
│ id       │     │ id         │     │ id            │
│ username │     │ title      │     │ incident_id   │
│ role     │     │ severity   │     │ unit_id       │
│ zone_h3  │     │ status     │     │ event_type    │
└──────────┘     │ h3_index ◆ │     │ timestamp     │
                 │ lat, lng   │     └───────┬───────┘
                 └────────────┘             │
                                    ┌───────▼───────┐
┌──────────┐                        │ ResponseUnit  │
│   Zone   │                        │               │
│          │                        │ id            │
│ id       │                        │ call_sign     │
│ h3_index◆│                        │ unit_type     │
│ name     │                        │ status        │
│ risk     │                        │ current_h3  ◆ │
└──────────┘                        │ zone_h3     ◆ │
                                    └───────────────┘
┌──────────────┐     ┌─────────────────┐
│  AuditLog    │     │ ZoneAnalytics   │
│              │     │                 │
│ id           │     │ id              │
│ timestamp    │     │ h3_index      ◆ │
│ user_id      │     │ period_start    │
│ action       │     │ total_incidents │
│ resource     │     │ critical_count  │
│ details      │     │ dispatches      │
└──────────────┘     └─────────────────┘

◆ = H3 indexed column
```

### Logical Schema (7 Tables)

| Table            | Key Columns                                                      |
|------------------|------------------------------------------------------------------|
| users            | id, username, hashed_password, role, assigned_zone_h3            |
| zones            | id, **h3_index** (unique), name, city, risk_level               |
| response_units   | id, call_sign, unit_type, status, current_h3, assigned_zone_h3  |
| incidents        | id, title, severity, status, reported_by, lat, lng, **h3_index**|
| dispatch_events  | id, incident_id, unit_id, event_type, timestamp, notes          |
| **audit_log**    | id, timestamp, user_id, action, resource_type, resource_id, details |
| **zone_analytics** | id, **h3_index**, period_start/end, total_incidents, critical, dispatches, resolved |

### Short Justification
- **audit_log** captures every sensitive action (login, incident creation, dispatch) for compliance.
- **zone_analytics** is a pre-aggregated table (materialized view pattern) allowing fast dashboard queries without scanning raw incident data.
- **H3 columns** enable O(1) zone lookup and efficient spatial filtering via `k_ring`.

---

## 4. Security & IAM Design

### Role List
| Role       | Description                              |
|------------|------------------------------------------|
| Admin      | Full system access, user management      |
| Dispatcher | Incident CRUD, dispatch units            |
| Responder  | View/update incidents in assigned zone   |
| Analyst    | Read-only analytics and incident data    |
| Auditor    | Read-only audit logs and dispatch history|

### Permission Matrix

| Permission        | Admin | Dispatcher | Responder | Analyst | Auditor |
|-------------------|:-----:|:----------:|:---------:|:-------:|:-------:|
| incident.create   |   ✓   |     ✓      |           |         |         |
| incident.read     |   ✓   |     ✓      |  ✓ (ABAC) |    ✓    |    ✓    |
| incident.update   |   ✓   |     ✓      |  ✓ (ABAC) |         |         |
| incident.delete   |   ✓   |            |           |         |         |
| unit.create       |   ✓   |            |           |         |         |
| unit.read         |   ✓   |     ✓      |     ✓     |    ✓    |         |
| unit.update       |   ✓   |     ✓      |           |         |         |
| dispatch.create   |   ✓   |     ✓      |           |         |         |
| dispatch.read     |   ✓   |     ✓      |     ✓     |    ✓    |    ✓    |
| zone.create       |   ✓   |            |           |         |         |
| zone.read         |   ✓   |     ✓      |     ✓     |    ✓    |         |
| analytics.read    |   ✓   |     ✓      |           |    ✓    |         |
| audit.read        |   ✓   |            |           |         |    ✓    |
| user.manage       |   ✓   |            |           |         |         |

### ABAC Rule
> **Zone-Restricted Access**: A user with role=`RESPONDER` can only read/update incidents whose `h3_index` is within the `k_ring(assigned_zone_h3, k=1)` set. If `incident.h3_index ∉ k_ring(user.assigned_zone_h3, 1)`, the request is denied with HTTP 403.

### Identified Vulnerability
> **Hardcoded JWT Secret**: The default `SECRET_KEY` in `config.py` is a static string. If an attacker gains access to the source code or environment, they can forge JWT tokens for any role (including admin). **Mitigation**: Use an external secrets manager and rotate keys periodically.

---

## 5. Coding Implementation Summary

| Requirement               | Implementation                                              |
|---------------------------|-------------------------------------------------------------|
| Backend framework         | FastAPI (Python 3.10+)                                      |
| SQL database              | SQLite via SQLAlchemy ORM (7 tables)                        |
| At least 5 endpoints      | **15+ endpoints** across 6 routers                          |
| Role-based access control | JWT + permission matrix + `require_permissions()` dependency|
| Event-driven simulation   | Async queue + background consumer in `events.py`            |
| Audit logging             | `audit_log` table — logs login, incident.create, dispatch   |
| Modular structure         | config / database / models / schemas / auth / routers / events |
| H3 integration            | Store `h3_index`, query by k-ring, aggregate by zone        |

---

## 6. Demo Script

### Step 1: Login
```
POST /auth/token  →  {"username":"dispatcher1","password":"disp123"}
→ Returns JWT token
```

### Step 2: Create Incident
```
POST /incidents/  →  {"title":"Gas leak","severity":"critical","latitude":51.17,"longitude":71.45}
→ H3 index auto-computed, audit logged
```

### Step 3: Dispatch Unit
```
POST /dispatch/  →  {"incident_id":1,"unit_id":1}
→ Event published → consumer updates statuses asynchronously
```

### Step 4: H3 Spatial Query
```
POST /incidents/h3-query  →  {"h3_index":"<zone>","k_ring":1}
→ Returns all incidents in hex + neighbors
```

### Step 5: RBAC Demo
```
Login as responder1 → can see only incidents in assigned zone
Login as auditor1  → can only access /audit/ endpoint
```

### Step 6: Audit Log
```
GET /audit/  →  Shows login events, incident creations, dispatches
```

### Step 7: Analytics
```
POST /analytics/refresh  →  Aggregates incidents per H3 zone
GET  /analytics/         →  View per-zone stats
```

---

## Why H3 is Appropriate

Emergency response is inherently **spatial**. H3 hexagons provide:
- **Uniform adjacency**: Every hex has exactly 6 neighbors → consistent "nearby zone" queries.
- **Multi-resolution**: Can zoom from city-wide (res 5) to neighborhood blocks (res 9).
- **Efficient indexing**: `O(1)` lat/lng → zone lookup vs. expensive polygon-in-polygon queries.
- **Fair partitioning**: Unlike square grids, hexagons have equal distance to all neighbors — ideal for balanced dispatch coverage and analytics aggregation.

---

*CERMS v1.0 — Information Systems Phase 2 Project*
