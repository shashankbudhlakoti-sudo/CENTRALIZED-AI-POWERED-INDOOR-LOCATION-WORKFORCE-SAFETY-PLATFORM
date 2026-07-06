# API Contract — Indoor Location & Workforce Safety Platform

Base URL (pilot): `http://localhost:8000/api/v1`
WebSocket: `ws://localhost:8000/ws`

## Auth

All requests (except `/health`) require:

```
Authorization: Bearer <keycloak_access_token>
```

Backend validates the JWT against Keycloak's realm public key, then sets Postgres session vars
(`app.current_department`, `app.current_role`) from token claims before running the query, so RLS
enforces isolation automatically.

Roles (from token `realm_access.roles`): `hr_manager`, `it_manager`, `finance_manager`,
`security_admin`, `general_manager`. Tier 3/4 roles (`security_admin`, `general_manager`) require
MFA (`acr` claim = `mfa`) — backend rejects tokens without it on protected endpoints.

---

## REST Endpoints

### Employees
| Method | Path | Notes |
|---|---|---|
| GET | `/employees` | List (department-scoped by RLS) |
| GET | `/employees/{id}` | Single record |
| POST | `/employees` | Create (hr_manager, security_admin) |
| PATCH | `/employees/{id}` | Update |
| POST | `/employees/{id}/consent` | Record consent capture |

**Employee object:**
```json
{
  "id": "uuid",
  "employee_code": "EMP-1042",
  "full_name": "string",
  "department": "string",
  "role_title": "string",
  "email": "string",
  "consent_given": true,
  "active": true
}
```

### Tags
| Method | Path | Notes |
|---|---|---|
| GET | `/tags` | List, filter by `?active=true` |
| POST | `/tags` | Register new beacon/badge |
| POST | `/tags/{id}/assign` | Body: `{ "employee_id": "uuid" }` |

### Zones
| Method | Path | Notes |
|---|---|---|
| GET | `/zones?floor=1` | Returns GeoJSON FeatureCollection |
| POST | `/zones` | Create zone polygon |

**Zone GeoJSON feature:**
```json
{
  "id": "uuid",
  "name": "Warehouse A - Restricted",
  "department": "logistics",
  "floor": 1,
  "zone_type": "restricted",
  "geometry": { "type": "Polygon", "coordinates": [[[0,0],[10,0],[10,10],[0,10],[0,0]]] }
}
```

### Positions (Track B mainly reads this)
| Method | Path | Notes |
|---|---|---|
| GET | `/positions/latest` | Latest position per active tag |
| GET | `/positions/history?employee_id=&from=&to=` | Historical playback data |
| POST | `/positions` | **Ingestion only** (Track A writes here from gateway) |

**Position event:**
```json
{
  "tag_id": "uuid",
  "employee_id": "uuid",
  "floor": 1,
  "x": 12.4,
  "y": 7.1,
  "accuracy_m": 1.8,
  "source": "filtered",
  "recorded_at": "2026-07-06T10:15:00Z"
}
```

### Checkpoints (shared feature — split seam)
| Method | Path | Owner | Notes |
|---|---|---|---|
| POST | `/checkpoints` | Track A | Camera trigger creates event + stores photo, `match_status=pending` |
| PATCH | `/checkpoints/{id}/match` | Track B | Writes `match_employee_id`, `match_confidence`, `match_status` |
| GET | `/checkpoints?status=mismatch` | shared | Dashboard review queue |

### Alerts
| Method | Path | Notes |
|---|---|---|
| GET | `/alerts?acknowledged=false` | Active alerts feed |
| POST | `/alerts` | Created by anomaly/rule engine (Track B) or ingestion (Track A) |
| POST | `/alerts/{id}/acknowledge` | Body: `{ "note": "string" }` |

### Audit Log (security_admin only)
| Method | Path | Notes |
|---|---|---|
| GET | `/audit-log?actor=&from=&to=` | Read access history |
| POST | `/access/break-glass` | Body: `{ "resource_type": "", "resource_id": "", "justification": "" }` → time-limited elevated token |

### Health
| Method | Path | Notes |
|---|---|---|
| GET | `/health` | No auth. `{ "status": "ok", "db": "ok", "mqtt": "ok" }` |

---

## WebSocket

`ws://localhost:8000/ws?token=<jwt>`

Server pushes JSON messages, department-filtered same as REST:

```json
{ "event": "position_update", "data": { "employee_id": "uuid", "x": 12.4, "y": 7.1, "floor": 1 } }
{ "event": "alert_created", "data": { "id": "uuid", "alert_type": "zone_breach", "severity": "critical", "employee_id": "uuid" } }
{ "event": "checkpoint_updated", "data": { "id": "uuid", "match_status": "match" } }
```

Client → server (subscribe to a floor or department, optional):
```json
{ "action": "subscribe", "floor": 1 }
```

---

## Error format (all endpoints)

```json
{ "error": { "code": "string", "message": "string" } }
```

Standard HTTP status codes: 400 (validation), 401 (auth), 403 (RLS/role denial), 404, 409 (conflict), 500.

---

## Change process

This file + `schema.sql` are the only files both tracks should need to touch together. If either
side needs a change, open a PR against `/contracts` and both people approve before merging —
that's the only expected source of merge conflicts in this repo.
