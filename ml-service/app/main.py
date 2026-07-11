from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import get_db, set_rls_context, engine
from app import models
from app.auth import get_current_user, CurrentUser

app = FastAPI(title="Indoor Location & Workforce Safety Platform API", version="0.1.0")

# CORS: allow local frontend dev servers to call this API from the browser.
# Vite defaults to 5173, Create React App to 3000 — allow both for now.
# Tighten this to the real deployed frontend origin before any real deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class CheckpointIn(BaseModel):
    zone_id: UUID
    tag_id: Optional[UUID] = None
    employee_id: Optional[UUID] = None
    photo_url: str


class CheckpointMatchIn(BaseModel):
    match_employee_id: Optional[UUID] = None
    match_confidence: Optional[float] = None
    match_status: str  # 'match' | 'mismatch' | 'no_face'


class AnomalyDetectIn(BaseModel):
    alert_type: str  # 'zone_breach' | 'inactivity' | 'tag_offline'
    employee_id: Optional[UUID] = None
    tag_id: Optional[UUID] = None
    zone_id: Optional[UUID] = None
    details: Optional[dict] = None


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


# ---------- Checkpoints (shared feature — split seam) ----------

@app.post("/api/v1/checkpoints", status_code=201)
def create_checkpoint(payload: CheckpointIn, db: Session = Depends(get_db)):
    """Track A: called by the camera-trigger service when someone passes a checkpoint.
    Creates the row with match_status='pending'; Track B's face-match service
    fills in the result afterward via PATCH /checkpoints/{id}/match."""
    cp = models.CheckpointEvent(**payload.model_dump())
    db.add(cp)
    db.commit()
    db.refresh(cp)
    return {"id": str(cp.id), "match_status": cp.match_status}


@app.patch("/api/v1/checkpoints/{checkpoint_id}/match")
def update_checkpoint_match(checkpoint_id: UUID, payload: CheckpointMatchIn, db: Session = Depends(get_db)):
    """Track B (ML service) calls this with the face-match result.
    The backend — not the ML service — decides whether this disagreement
    warrants an alert, and owns the single write path into `alerts`."""
    cp = db.get(models.CheckpointEvent, checkpoint_id)
    if not cp:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "Checkpoint event not found"}})

    cp.match_employee_id = payload.match_employee_id
    cp.match_confidence = payload.match_confidence
    cp.match_status = payload.match_status
    cp.resolved_at = datetime.utcnow()

    # Decide, server-side, whether this is a mismatch worth alerting on:
    # either the face-match explicitly failed, or it succeeded but disagrees
    # with who the tag is actually assigned to (possible badge sharing/tailgating).
    tag_owner_id = None
    if cp.tag_id:
        tag = db.get(models.Tag, cp.tag_id)
        tag_owner_id = tag.employee_id if tag else None

    is_mismatch = (
        payload.match_status in ("mismatch", "no_face")
        or (payload.match_status == "match" and tag_owner_id is not None and payload.match_employee_id != tag_owner_id)
    )

    if is_mismatch:
        alert = models.Alert(
            alert_type="checkpoint_mismatch",
            severity="critical" if payload.match_status != "no_face" else "warning",
            employee_id=tag_owner_id or payload.match_employee_id,
            zone_id=cp.zone_id,
            details={
                "checkpoint_event_id": str(cp.id),
                "match_status": payload.match_status,
                "match_confidence": payload.match_confidence,
                "match_employee_id": str(payload.match_employee_id) if payload.match_employee_id else None,
                "tag_owner_employee_id": str(tag_owner_id) if tag_owner_id else None,
            },
        )
        db.add(alert)

    db.commit()
    return {"status": "updated", "alert_created": is_mismatch}


@app.get("/api/v1/checkpoints")
def list_checkpoints(status: Optional[str] = None, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    set_rls_context(db, user.department, user.role)
    q = select(models.CheckpointEvent)
    if status:
        q = q.where(models.CheckpointEvent.match_status == status)
    rows = db.execute(q.order_by(models.CheckpointEvent.triggered_at.desc())).scalars().all()
    return [
        {
            "id": str(r.id), "zone_id": str(r.zone_id), "photo_url": r.photo_url,
            "match_status": r.match_status, "match_confidence": r.match_confidence,
            "match_employee_id": str(r.match_employee_id) if r.match_employee_id else None,
            "triggered_at": r.triggered_at.isoformat(),
        }
        for r in rows
    ]


# ---------- Anomalies (ML service reports, backend owns the alerts write) ----------

VALID_ANOMALY_TYPES = {"zone_breach", "inactivity", "tag_offline"}

# Severity defaults per anomaly type — tune as real-world data comes in.
ANOMALY_SEVERITY = {
    "zone_breach": "critical",
    "inactivity": "warning",
    "tag_offline": "warning",
}


@app.post("/api/v1/anomalies/detect", status_code=201)
def report_anomaly(payload: AnomalyDetectIn, db: Session = Depends(get_db)):
    """Called by the ML service's periodic sweep / real-time detectors.
    The ML service reports what it detected; the backend decides severity
    and owns the single write path into `alerts` — same pattern as
    checkpoint_mismatch. Auth for this endpoint should be the ml-service
    Keycloak client (client_credentials grant), not a human user token."""
    if payload.alert_type not in VALID_ANOMALY_TYPES:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "invalid_alert_type", "message": f"alert_type must be one of {sorted(VALID_ANOMALY_TYPES)}"}},
        )

    alert = models.Alert(
        alert_type=payload.alert_type,
        severity=ANOMALY_SEVERITY.get(payload.alert_type, "warning"),
        employee_id=payload.employee_id,
        zone_id=payload.zone_id,
        details={
            **(payload.details or {}),
            "tag_id": str(payload.tag_id) if payload.tag_id else None,
            "reported_by": "ml_service",
        },
    )
<<<<<<< HEAD
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return {"id": str(alert.id), "alert_type": alert.alert_type, "severity": alert.severity}


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
=======


# ---------------------------------------------------------------------------
# Face enrollment (employees.face_embedding)
#
# PROPOSED design, NOT YET CONFIRMED with Shashank - unlike every other
# write-path pattern in this file, this one hasn't been discussed with him
# yet. Flagging the open decisions rather than silently picking one:
#
# 1. Role gate: allowing BOTH security_admin and hr_manager for now, since
#    it's genuinely unclear which should own enrollment. Narrow this once
#    he decides - see require_role's multi-role support added for this.
# 2. Re-enrollment: this endpoint always generates and returns a fresh
#    embedding: it doesn't know or care whether employee_id already has
#    one. Overwrite-vs-reject on re-enrollment is the BACKEND's decision
#    when it writes employees.face_embedding, not something this service
#    can decide since it never reads or writes that table itself.
# 3. Who captures the enrollment photo (HR onboarding flow? manual admin
#    upload?) is entirely a backend/frontend workflow question - this
#    endpoint only needs a photo_url, however it got there.
#
# Reuses the exact same EmbeddingGenerator as checkpoint verification - no
# new face-processing code, just a thin endpoint + audit logging. This
# service never writes to employees.face_embedding directly - same
# single-write-path pattern as positions/checkpoints/alerts: the backend
# takes this response and owns the actual write.
# ---------------------------------------------------------------------------


class EnrollFaceRequest(BaseModel):
    employee_id: str
    photo_url: str


class EnrollFaceResult(BaseModel):
    employee_id: str
    status: str  # 'enrolled' | 'no_face'
    embedding: Optional[list[float]] = None


@app.post(
    "/internal/enroll-face",
    response_model=EnrollFaceResult,
    dependencies=[Depends(require_role("security_admin", "hr_manager"))],
)
async def enroll_face(
    req: EnrollFaceRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    async with httpx.AsyncClient(timeout=10.0) as client:
        photo_resp = await client.get(req.photo_url)
        photo_resp.raise_for_status()
        photo_bytes = photo_resp.content

    embedding = await _embedding_generator.generate(photo_bytes)

    # Enrollment writes biometric data to a specific employee's record -
    # logged regardless of outcome, same as checkpoint_verify. actor_role
    # reflects whichever of the two allowed roles this caller actually
    # has (security_admin preferred if they somehow have both).
    actor_role = "security_admin" if user.has_role("security_admin") else "hr_manager"
    await log_action(
        actor_user_id=user.sub,
        actor_role=actor_role,
        action="enroll_face",
        resource_type="employees",
        resource_id=req.employee_id,
        justification="face enrollment" if embedding is not None else "face enrollment failed: no face detected",
    )

    if embedding is None:
        return EnrollFaceResult(employee_id=req.employee_id, status="no_face", embedding=None)

    return EnrollFaceResult(
        employee_id=req.employee_id,
        status="enrolled",
        embedding=embedding.tolist(),
    )

# ---------------------------------------------------------------------------
# Login Anomaly Detection Pipeline
# ---------------------------------------------------------------------------

_login_state = LoginAnomalyState()

class LoginCheckRequest(BaseModel):
    employee_id: str = Field(..., max_length=64)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    timestamp: float
    client_ip: Optional[str] = None


class LoginCheckResult(BaseModel):
    employee_id: str
    is_anomalous: bool
    details: dict


@app.post("/internal/check-login", response_model=LoginCheckResult)
async def check_login_anomaly(
    req: LoginCheckRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Evaluates incoming login metadata for impossible velocity constraints.
    If flagged, it synchronously dispatches a non-blocking alert report to the
    centralized backend metrics registry."""
    is_anomalous, details = _login_state.check_travel_anomaly(
        employee_id=req.employee_id,
        lat=req.latitude,
        lon=req.longitude,
        timestamp=req.timestamp
    )

    if is_anomalous:
        logger.warning("Impossible travel anomaly detected for employee=%s: %s", req.employee_id, details)
        try:
            if req.client_ip:
                details["client_ip"] = req.client_ip
                
            await report_anomaly(
                alert_type="impossible_travel",
                bearer_token=user.raw_token,
                employee_id=req.employee_id,
                details=details,
            )
        except Exception:
            logger.exception("Failed to dispatch impossible_travel anomaly alert for employee=%s", req.employee_id)

    return LoginCheckResult(
        employee_id=req.employee_id,
        is_anomalous=is_anomalous,
        details=details
    )
>>>>>>> cf688d0674c91791740b1ebe2631dd1f86867bcf
