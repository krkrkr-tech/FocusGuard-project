# CERMS — City Emergency Response Management System
## Phase 2: Institutional Information System Report

**Domain:** Urban Infrastructure — Emergency Response  
**City:** Astana, Kazakhstan  
**Date:** February 2026

---

## 1. Framing & Stakeholders

### 1.1 Problem Statement

Astana's emergency services (police, fire, ambulance) currently operate with fragmented coordination. When a citizen reports an emergency, dispatchers must manually determine which response unit is closest, whether that unit is available, and which geographic zone the incident falls in. This leads to delayed response times, duplicate dispatches, and a lack of accountability in record-keeping.

CERMS solves this by providing a single digital platform that automates spatial awareness (which unit is nearest?), enforces role-based workflows (who is allowed to do what?), and maintains a full audit trail of every action taken.

### 1.2 Stakeholders

| Stakeholder | System Role | Needs & Goals |
|---|---|---|
| City Emergency Department (Akimat) | Admin | Full oversight of all operations, user management, zone configuration |
| Dispatch Center Operators | Dispatcher | Quickly create incidents, assign the right unit, track status in real time |
| Field Responders (Police, Fire, EMS) | Responder | View only incidents in their assigned zone, update status on scene |
| City Safety Analysts | Analyst | Read-only access to incident data and zone analytics for reporting |
| Compliance & Internal Audit Office | Auditor | Review immutable audit logs for accountability and legal compliance |
| Citizens of Astana | (External) | Faster emergency response times and transparent public safety |

### 1.3 Key Business Rules

1. Every incident is geolocated — latitude/longitude is converted to an H3 hexagonal zone automatically.
2. A responder can only see and update incidents within their assigned zone (and its immediate neighbors). This is Attribute-Based Access Control (ABAC).
3. Every sensitive action (login, incident creation, dispatch assignment) is recorded in an immutable audit log.
4. When a dispatch is created, an asynchronous event is published so that unit and incident statuses update automatically without blocking the dispatcher.

---

## 2. Architecture

### 2.1 Architecture Style: Monolith with Event-Driven Component

CERMS uses a **modular monolith** architecture. All modules run within a single FastAPI process, sharing one SQLite database. This was chosen because:

- The system is operated by a single city department (one team, one deployment).
- Network latency between microservices would add unnecessary complexity for a city-scale system.
- A monolith is simpler to deploy, test, and debug for a team of this size.

The **event-driven component** (asyncio.Queue) sits inside the monolith and processes dispatch events asynchronously. This decouples the dispatcher's HTTP request from the side effects (updating unit/incident status, writing audit logs).

### 2.2 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        CERMS Monolith                           │
│                     (FastAPI + Uvicorn)                          │
│                                                                 │
│  ┌──────────┐  ┌───────────┐  ┌─────────┐  ┌───────────────┐   │
│  │   Auth   │  │ Incidents │  │  Units  │  │   Dispatch    │   │
│  │  Router  │  │   Router  │  │ Router  │  │    Router     │   │
│  └────┬─────┘  └─────┬─────┘  └────┬────┘  └──────┬────────┘   │
│       │              │             │               │            │
│  ┌──────────┐  ┌───────────┐  ┌─────────┐  ┌──────────────┐    │
│  │  Zones   │  │  Audit    │  │   H3    │  │  Event Queue │    │
│  │  Router  │  │  Router   │  │  Utils  │  │  (asyncio)   │    │
│  └────┬─────┘  └─────┬─────┘  └────┬────┘  └──────┬───────┘    │
│       │              │             │               │            │
│       └──────────────┴─────────────┴───────────────┘            │
│                           │                                     │
│                    ┌──────┴──────┐                               │
│                    │  SQLAlchemy │                               │
│                    │     ORM     │                               │
│                    └──────┬──────┘                               │
│                           │                                     │
└───────────────────────────┼─────────────────────────────────────┘
                            │
                     ┌──────┴──────┐
                     │   SQLite    │
                     │  cerms.db   │
                     └─────────────┘
```

### 2.3 Event-Driven Flow

```
Dispatcher calls POST /dispatch/
        │
        ▼
┌─────────────────────┐
│ 1. Validate incident │
│ 2. Validate unit     │
│ 3. Create DB record  │
│ 4. Write audit log   │
│ 5. Return 201 JSON   │──────► HTTP response to dispatcher
└─────────┬───────────┘
          │
          ▼
  publish_event() ──► asyncio.Queue
                          │
                          ▼
                  ┌───────────────────┐
                  │  Event Consumer   │
                  │  (background)     │
                  │                   │
                  │ • Unit → DISPATCHED│
                  │ • Incident → DISPATCHED│
                  │ • Write audit log │
                  └───────────────────┘
```

### 2.4 Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Web Framework | FastAPI 0.104.1 | Async-capable REST API with auto-generated Swagger docs |
| ORM | SQLAlchemy 2.0.23 | Object-Relational Mapping for all 7 database tables |
| Database | SQLite | Lightweight, zero-config relational database |
| Auth | python-jose + passlib | JWT token generation/validation + bcrypt password hashing |
| Spatial Indexing | H3 3.7.7 (Uber) | Hexagonal hierarchical spatial index |
| Validation | Pydantic 2.5.2 | Request/response schema validation |
| Event Queue | asyncio.Queue | In-process async event bus for dispatch events |

---

## 3. Data Model

### 3.1 Entity-Relationship Diagram

```
┌──────────────┐       ┌──────────────────┐       ┌─────────────────┐
│    users     │       │    incidents     │       │ response_units  │
├──────────────┤       ├──────────────────┤       ├─────────────────┤
│ id (PK)      │       │ id (PK)          │       │ id (PK)         │
│ username     │◄──┐   │ title            │   ┌──►│ call_sign       │
│ hashed_pwd   │   │   │ description      │   │   │ unit_type       │
│ full_name    │   │   │ severity         │   │   │ status          │
│ role (enum)  │   │   │ status           │   │   │ current_lat     │
│ is_active    │   └───│ reported_by (FK) │   │   │ current_lng     │
│ created_at   │       │ latitude         │   │   │ current_h3      │
│ assigned_    │       │ longitude        │   │   │ assigned_zone_h3│
│  zone_h3     │       │ h3_index         │   │   └─────────────────┘
└──────────────┘       │ created_at       │   │
                       │ updated_at       │   │
                       └────────┬─────────┘   │
                                │             │
                       ┌────────┴─────────┐   │
                       │ dispatch_events  │   │
                       ├──────────────────┤   │
                       │ id (PK)          │   │
                       │ incident_id (FK)─┘   │
                       │ unit_id (FK)─────────┘
                       │ event_type            
                       │ timestamp             
                       │ notes                 
                       └──────────────────┘

┌──────────────────┐       ┌──────────────────┐
│    audit_log     │       │ zone_analytics   │
├──────────────────┤       ├──────────────────┤
│ id (PK)          │       │ id (PK)          │
│ timestamp        │       │ h3_index         │
│ user_id (FK)     │       │ period_start     │
│ username         │       │ period_end       │
│ action           │       │ total_incidents  │
│ resource_type    │       │ critical_incidents│
│ resource_id      │       │ avg_response_min │
│ details          │       │ dispatches       │
│ ip_address       │       │ resolved         │
└──────────────────┘       └──────────────────┘

┌──────────────┐
│    zones     │
├──────────────┤
│ id (PK)      │
│ h3_index     │
│ name         │
│ city         │
│ risk_level   │
│ created_at   │
└──────────────┘
```

**Total: 7 tables**, connected by foreign keys between users → incidents → dispatch_events ← response_units.

### 3.2 H3 Spatial Indexing — Explanation

**What is H3?**  
H3 is a geospatial indexing system created by Uber that divides the entire Earth's surface into hexagonal cells at multiple resolutions. Each cell has a unique string identifier (e.g., `872153821ffffff`).

**Why hexagons?**  
Unlike square grids, hexagons have uniform adjacency — every neighbor is equidistant from the center. This eliminates the distortion problem of square grids and makes distance-based queries more accurate. This is critical for emergency response where "nearest unit" calculations must be reliable.

**How CERMS uses H3:**

| Operation | How H3 is used |
|---|---|
| Incident creation | `lat_lng_to_h3(lat, lng)` converts GPS coordinates to an H3 cell ID (resolution 7, ~5.16 km² per hex) |
| Unit tracking | Each response unit's current GPS position is converted to an H3 cell to know which zone it is in |
| ABAC zone filtering | A responder's `assigned_zone_h3` is compared with the incident's `h3_index` using k-ring neighbors |
| Spatial query | `POST /incidents/h3-query` finds all incidents within a hex and its k-ring neighbors |
| Analytics aggregation | `POST /analytics/refresh` groups incidents and dispatches by H3 zone for statistical analysis |

**Resolution 7 specifics:**
- Each hexagon covers approximately **5.16 km²**
- Astana (~800 km² urban area) is covered by roughly **150–200 hexagons**
- This is granular enough for neighborhood-level dispatch without creating too many zones

**k-ring query example:**  
When `k=1`, the system checks the center hex plus its 6 immediate neighbors (7 hexes total). This ensures a responder assigned to a zone can also see incidents just across the border.

```
        ╱╲     ╱╲
      ╱    ╲ ╱    ╲
     │  N1  │  N2  │
      ╲    ╱ ╲    ╱
  ╱╲   ╲╱     ╲╱   ╱╲
╱    ╲ ╱╲     ╱╲ ╱    ╲
│  N6 │  CENTER │  N3  │
╲    ╱ ╲╱     ╲╱ ╲    ╱
  ╲╱   ╱╲     ╱╲   ╲╱
      ╱    ╲ ╱    ╲
     │  N5  │  N4  │
      ╲    ╱ ╲    ╱
        ╲╱     ╲╱
```

---

## 4. Security & Identity Access Management (IAM)

### 4.1 Authentication: JWT Bearer Tokens

Users authenticate by sending their username and password to `POST /auth/token`. The server:

1. Verifies the password against the bcrypt hash stored in the database.
2. Generates a JWT (JSON Web Token) containing the user's username and role.
3. Returns the token with a 60-minute expiry.

Every subsequent API call must include this token in the `Authorization: Bearer <token>` header. The server decodes and validates the token on each request.

**Token payload structure:**
```json
{
  "sub": "dispatcher1",
  "role": "dispatcher",
  "exp": 1740600000
}
```

### 4.2 RBAC — Role-Based Access Control

The system defines 5 roles, each with a specific set of permissions:

| Permission | Admin | Dispatcher | Responder | Analyst | Auditor |
|---|:---:|:---:|:---:|:---:|:---:|
| incident.create | ✓ | ✓ | — | — | — |
| incident.read | ✓ | ✓ | ✓ (zone) | ✓ | ✓ |
| incident.update | ✓ | ✓ | ✓ (zone) | — | — |
| incident.delete | ✓ | — | — | — | — |
| unit.create | ✓ | — | — | — | — |
| unit.read | ✓ | ✓ | ✓ | ✓ | — |
| unit.update | ✓ | ✓ | — | — | — |
| dispatch.create | ✓ | ✓ | — | — | — |
| dispatch.read | ✓ | ✓ | ✓ | ✓ | ✓ |
| zone.create | ✓ | — | — | — | — |
| zone.read | ✓ | ✓ | ✓ | ✓ | — |
| zone.update | ✓ | — | — | — | — |
| analytics.read | ✓ | ✓ | — | ✓ | — |
| audit.read | ✓ | — | — | — | ✓ |
| user.manage | ✓ | — | — | — | — |

**Implementation:** A `PERMISSION_MATRIX` dictionary maps each role to its allowed permissions. The `require_permissions()` dependency factory checks if the authenticated user's role has the required permission before executing any endpoint.

### 4.3 ABAC — Attribute-Based Access Control

RBAC alone is not sufficient. A responder should not see incidents from across the city — only those in their assigned zone. ABAC adds this spatial restriction:

**Rule:** If the user's role is `RESPONDER`, the system checks whether the incident's `h3_index` falls within the `k_ring(user.assigned_zone_h3, k=1)` set. If not, the request is denied with HTTP 403.

**Example:**
- `responder1` is assigned to zone `872153821ffffff` (Astana City Center)
- Incident #1 has `h3_index = 872153821ffffff` → **allowed** (same zone)
- Incident #2 has `h3_index = 872153806ffffff` → **allowed** (k=1 neighbor)
- Incident #3 has `h3_index = 87215381affffff` → **denied** (outside zone + neighbors)

### 4.4 Audit Logging

Every sensitive action is recorded in the `audit_log` table with:

- **timestamp** — when the action occurred (UTC)
- **user_id / username** — who performed it
- **action** — what was done (e.g., `auth.login`, `incident.create`, `dispatch.create`)
- **resource_type / resource_id** — which entity was affected
- **details** — JSON string with additional context

The audit log is **append-only** — there is no update or delete endpoint. Only users with the `audit.read` permission (admin and auditor) can view it.

### 4.5 Security Summary

| Security Layer | Mechanism | Implementation |
|---|---|---|
| Authentication | JWT Bearer Token | `python-jose` library, 60-min expiry, HS256 signing |
| Password Storage | bcrypt hash | `passlib` library, never stored in plaintext |
| Authorization (RBAC) | Permission matrix | 5 roles × 15 permissions, checked on every endpoint |
| Authorization (ABAC) | H3 zone filtering | Responders restricted to assigned zone + k=1 neighbors |
| Audit Trail | Immutable log table | Every login, create, dispatch, and resolve is recorded |
| Input Validation | Pydantic schemas | All request bodies validated with type checks and constraints |

---

## 5. API Endpoints Summary

| # | Method | Endpoint | Description |
|---|---|---|---|
| 1 | GET | / | System info |
| 2 | POST | /auth/token | Login, get JWT token |
| 3 | GET | /auth/me | Current user profile |
| 4 | POST | /incidents/ | Create incident |
| 5 | GET | /incidents/ | List incidents |
| 6 | GET | /incidents/{id} | Get single incident |
| 7 | PUT | /incidents/{id} | Update incident |
| 8 | POST | /incidents/h3-query | Spatial query by H3 |
| 9 | POST | /units/ | Create response unit |
| 10 | GET | /units/ | List units |
| 11 | GET | /units/{id} | Get single unit |
| 12 | PUT | /units/{id} | Update unit |
| 13 | POST | /dispatch/ | Dispatch unit to incident |
| 14 | GET | /dispatch/ | List dispatch events |
| 15 | POST | /dispatch/resolve | Resolve a dispatch |
| 16 | GET | /audit/ | View audit logs |
| 17 | POST | /zones/ | Create zone |
| 18 | GET | /zones/ | List zones |
| 19 | GET | /zones/h3-info | H3 resolution metadata |
| 20 | GET | /analytics/ | View zone analytics |
| 21 | POST | /analytics/refresh | Recompute analytics |

**Total: 21 endpoints** across 7 routers.
