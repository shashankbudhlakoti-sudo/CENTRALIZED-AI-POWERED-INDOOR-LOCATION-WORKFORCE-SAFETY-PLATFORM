from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import get_db, set_rls_context, engine
from app import models
from app.auth import get_current_user, CurrentUser

app = FastAPI(title="Indoor Location & Workforce Safety Platform API", version="0.1.0")


# ---------- Pydantic schemas (mirrors contracts/api-spec.md) ----------

class EmployeeIn(BaseModel):
    employee_code: str
    full_name: str
    department: str
    role_title: Optional[str] = None
    email: Optional[str] = None


class PositionIn(BaseModel):
    tag_id: UUID
    employee_id: Optional[UUID] = None
    floor: int = 1
    x: float
    y: float
    accuracy_m: Optional[float] = None
    source: str = "filtered"


class AlertAck(BaseModel):
    note: Optional[str] = None


# ---------- Health ----------

@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {"status": "ok", "db": db_status, "mqtt": "not_checked"}


# ---------- Employees ----------

@app.get("/api/v1/employees")
def list_employees(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    set_rls_context(db, user.department, user.role)
    rows = db.execute(select(models.Employee)).scalars().all()
    return [
        {
            "id": str(r.id), "employee_code": r.employee_code, "full_name": r.full_name,
            "department": r.department, "role_title": r.role_title, "email": r.email,
            "consent_given": r.consent_given, "active": r.active,
        }
        for r in rows
    ]


@app.post("/api/v1/employees", status_code=201)
def create_employee(payload: EmployeeIn, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role not in ("hr_manager", "security_admin"):
        raise HTTPException(status_code=403, detail={"error": {"code": "forbidden", "message": "Not permitted to create employees"}})
    set_rls_context(db, user.department, user.role)
    emp = models.Employee(**payload.model_dump())
    db.add(emp)
    db.commit()
    db.refresh(emp)
    return {"id": str(emp.id)}


# ---------- Positions ----------

@app.get("/api/v1/positions/latest")
def latest_positions(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    set_rls_context(db, user.department, user.role)
    sql = text("""
        SELECT DISTINCT ON (tag_id) tag_id, employee_id, floor, x, y, accuracy_m, recorded_at
        FROM position_events
        ORDER BY tag_id, recorded_at DESC
    """)
    rows = db.execute(sql).mappings().all()
    return [dict(r) for r in rows]


@app.post("/api/v1/positions", status_code=201)
def ingest_position(payload: PositionIn, db: Session = Depends(get_db)):
    """Ingestion-only endpoint: called by the gateway (app/ or ingestion/ service),
    authenticated separately via a service token/mTLS in production — not the
    interactive-user Keycloak flow. Left unauthenticated here for local dev."""
    pe = models.PositionEvent(**payload.model_dump())
    db.add(pe)
    db.commit()
    return {"status": "recorded"}


# ---------- Alerts ----------

@app.get("/api/v1/alerts")
def list_alerts(acknowledged: Optional[bool] = None, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    set_rls_context(db, user.department, user.role)
    q = select(models.Alert)
    if acknowledged is not None:
        q = q.where(models.Alert.acknowledged == acknowledged)
    rows = db.execute(q.order_by(models.Alert.created_at.desc())).scalars().all()
    return [
        {
            "id": str(r.id), "alert_type": r.alert_type, "severity": r.severity,
            "employee_id": str(r.employee_id) if r.employee_id else None,
            "acknowledged": r.acknowledged, "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@app.post("/api/v1/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: UUID, payload: AlertAck, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    set_rls_context(db, user.department, user.role)
    alert = db.get(models.Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Alert not found"}})
    alert.acknowledged = True
    alert.acknowledged_by = user.user_id
    alert.acknowledged_at = datetime.utcnow()
    db.commit()
    return {"status": "acknowledged"}


# ---------- WebSocket ----------

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict):
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Client can send {"action": "subscribe", "floor": 1} — filtering
            # logic to be added once frontend (Track B) defines its needs.
            _ = await websocket.receive_json()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
