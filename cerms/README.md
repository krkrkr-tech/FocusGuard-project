# CERMS – City Emergency Response Management System

## Domain
**Urban Infrastructure – Emergency Response Coordination**

Astana city's emergency services (police, fire, ambulance) need a centralized system to report incidents, dispatch response units to geographic zones, track resolution, and maintain an audit trail under institutional constraints.

---

## Quick Start

```bash
cd cerms
pip install -r requirements.txt

# Seed the database with sample data
python seed.py

# Start the server
uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000/docs** for the interactive Swagger UI.

---

## Project Structure

```
cerms/
├── app/
│   ├── __init__.py
│   ├── main.py            ← FastAPI app + lifespan (startup/shutdown)
│   ├── config.py           ← Settings (DB URL, JWT, H3 resolution)
│   ├── database.py         ← SQLAlchemy engine + session
│   ├── models.py           ← ORM models (7 tables)
│   ├── schemas.py          ← Pydantic request/response schemas
│   ├── auth.py             ← JWT auth, RBAC, ABAC, permission matrix
│   ├── h3_utils.py         ← H3 spatial indexing utilities
│   ├── events.py           ← Async event queue + consumer (event-driven)
│   └── routers/
│       ├── __init__.py
│       ├── auth_router.py  ← POST /auth/token, GET /auth/me
│       ├── incidents.py    ← CRUD incidents, H3 spatial query
│       ├── units.py        ← CRUD response units
│       ├── dispatch.py     ← Dispatch + resolve (event-driven)
│       ├── audit.py        ← Audit log retrieval
│       └── zones.py        ← Zone management + analytics
├── seed.py                 ← Database seeding script
├── requirements.txt
└── README.md
```

---

## Seed Users

| Username    | Password    | Role        |
|-------------|-------------|-------------|
| admin       | admin123    | Admin       |
| dispatcher1 | disp123     | Dispatcher  |
| responder1  | resp123     | Responder   |
| responder2  | resp123     | Responder   |
| analyst1    | analyst123  | Analyst     |
| auditor1    | audit123    | Auditor     |

---

## API Endpoints (15 total)

| Method | Path                   | Description                        | Min Role       |
|--------|------------------------|------------------------------------|----------------|
| GET    | /                      | System info                        | Public         |
| POST   | /auth/token            | Login → JWT                        | Public         |
| GET    | /auth/me               | Current user info                  | Any authed     |
| POST   | /incidents/            | Create incident                    | Dispatcher+    |
| GET    | /incidents/            | List incidents (H3 filter)         | Any authed     |
| GET    | /incidents/{id}        | Get single incident                | Any authed     |
| PUT    | /incidents/{id}        | Update incident                    | Dispatcher+    |
| POST   | /incidents/h3-query    | Spatial query by H3 + k-ring       | Any authed     |
| POST   | /units/                | Register response unit             | Admin          |
| GET    | /units/                | List units                         | Any authed     |
| GET    | /units/{id}            | Get unit                           | Any authed     |
| PUT    | /units/{id}            | Update unit status/location        | Dispatcher+    |
| POST   | /dispatch/             | Dispatch unit → incident (event)   | Dispatcher+    |
| GET    | /dispatch/             | List dispatch events               | Any authed     |
| POST   | /dispatch/resolve      | Resolve dispatch (event)           | Dispatcher+    |
| GET    | /audit/                | List audit logs                    | Admin/Auditor  |
| POST   | /zones/                | Create zone                        | Admin          |
| GET    | /zones/                | List zones                         | Any authed     |
| GET    | /zones/h3-info         | H3 resolution metadata             | Any authed     |
| GET    | /analytics/            | Zone analytics                     | Analyst+       |
| POST   | /analytics/refresh     | Recompute analytics from raw data  | Analyst+       |

---

## H3 Integration

- **Resolution 7** (~5.16 km² per hex) — suitable for city-scale zoning.
- Every incident auto-computes its `h3_index` from `(latitude, longitude)`.
- Response units track their `current_h3` and `assigned_zone_h3`.
- **Spatial queries**: `POST /incidents/h3-query` finds incidents within a hex + k-ring neighbors.
- **ABAC rule**: Responders can only access incidents in their assigned zone's k=1 ring.
- **Analytics aggregation** is grouped by H3 zone.

---

## Security & IAM

### Roles
Admin, Dispatcher, Responder, Analyst, Auditor

### Permission Matrix
See `app/auth.py` — `PERMISSION_MATRIX` dict.

### ABAC Rule
> A Responder can only view/update incidents whose `h3_index` falls within their `assigned_zone_h3` k=1 neighborhood.

### Identified Vulnerability
> **JWT Secret in Config**: The JWT signing key defaults to a hardcoded string in `config.py`. In production, this must come from a secrets manager (e.g., AWS Secrets Manager, HashiCorp Vault). An attacker who extracts this key can forge tokens for any role.

---

## Event-Driven Architecture

- `app/events.py` implements an **async in-process event queue** (simulates a message broker like RabbitMQ/Kafka).
- When a dispatch is created, an event is published to the queue.
- A **background consumer** processes events: updates unit status, incident status, and writes an audit entry.
- Resolve events free the unit back to `AVAILABLE`.

---

## Demo Flow

```bash
# 1. Login as dispatcher
curl -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"dispatcher1","password":"disp123"}'

# 2. Create incident
curl -X POST http://localhost:8000/incidents/ \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"title":"Gas leak downtown","severity":"high","latitude":51.17,"longitude":71.45}'

# 3. Dispatch a unit
curl -X POST http://localhost:8000/dispatch/ \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"incident_id":1,"unit_id":1,"notes":"Urgent response"}'

# 4. Query incidents by H3 zone
curl -X POST http://localhost:8000/incidents/h3-query \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"h3_index":"872d4b620ffffff","k_ring":1}'

# 5. Check audit log (as admin/auditor)
curl http://localhost:8000/audit/ -H "Authorization: Bearer <ADMIN_TOKEN>"

# 6. Refresh analytics
curl -X POST http://localhost:8000/analytics/refresh \
  -H "Authorization: Bearer <TOKEN>"
```
