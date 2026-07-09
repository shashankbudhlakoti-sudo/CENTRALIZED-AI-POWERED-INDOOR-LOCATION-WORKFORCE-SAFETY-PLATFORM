"""
ML service entry point.

Security posture:
- Every data-touching route requires a verified Keycloak JWT (app.security.auth).
- CORS is locked to the known frontend origin only - no wildcard.
- No route ever accepts a raw employee_id from the frontend for scope
  filtering; the JWT's own claims determine what a caller may query, and the
  backend has already scoped what it forwards here.
- Structured logging - no raw PII (photos, exact coordinates) ever hits logs.
"""

import logging
import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from pathlib import Path

from app.security.auth import AuthenticatedUser, get_current_user, require_role
from app.security.audit import log_action
from app.models.position_filter import PositionFilterRegistry
from app.models.train_mode import TrainingWalk, LabeledSample
from app.models.fingerprinting import FingerprintModel
from app.models.face_match import find_best_match
from app.services.embedding_backend import EmbeddingGenerator, InsightFaceEmbeddingGenerator
from app.services.enrolled_embeddings_repo import EnrolledEmbeddingsRepository, PostgresEnrolledEmbeddings
from app.services.checkpoint_client import patch_checkpoint_match
from app.services import zone_repo
from app.services.anomaly_client import report_anomaly
from app.services import tag_offline_sweep
from app.models.anomaly_state import ZoneBreachState, InactivityState
from typing import Optional
import asyncio
import time
import httpx
from contextlib import asynccontextmanager

MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/data/models"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("ml-service")

ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if not ALLOWED_ORIGINS:
    raise RuntimeError("ALLOWED_ORIGINS must be set explicitly - refusing to default to '*'")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # tag_offline detection runs on a timer, not per-request (see
    # tag_offline_sweep.py docstring for why) - started alongside the app
    # and cancelled cleanly on shutdown rather than left as an orphaned task.
    sweep_task = asyncio.create_task(tag_offline_sweep.run_forever())
    try:
        yield
    finally:
        sweep_task.cancel()
        try:
            await sweep_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Indoor Tracking ML Service", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

registry = PositionFilterRegistry()


@app.get("/health")
async def health():
    # Deliberately unauthenticated - used by Docker/orchestration health
    # checks only. Returns no data, just process liveness.
    return {"status": "ok"}


class RawPositionReading(BaseModel):
    tag_id: str = Field(..., max_length=64)
    x_meas: float
    y_meas: float
    timestamp: float
    confidence: float = Field(1.0, ge=0.0, le=1.0)


class FilteredPosition(BaseModel):
    tag_id: str
    x: float
    y: float
    accuracy_m: float  # estimated positioning error in meters, matches
    # position_events.accuracy_m. Distinct from checkpoint_events.match_confidence
    # (face-match score) - do not conflate the two.


_zone_breach_state = ZoneBreachState()
_inactivity_state = InactivityState()

# Placeholder - needs real calibration once we know how still is "normal"
# for someone standing at a desk/checkpoint vs. genuinely incapacitated.
INACTIVITY_THRESHOLD_SECONDS = 300


@app.post("/internal/filter-position", response_model=FilteredPosition)
async def filter_position(
    reading: RawPositionReading,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Called by the ingestion pipeline (via the backend) with one raw
    trilaterated reading; returns the Kalman-smoothed position.

    Note: this endpoint is internal-service-to-service traffic (backend ->
    ML service), not something the React frontend calls directly. It still
    requires a verified token because the network boundary alone is never
    treated as sufficient authorization.

    Also runs the two real-time anomaly checks (zone_breach, inactivity)
    synchronously here - this is the one place the ML service sees every
    position update as it happens. Each check is wrapped so a failure in
    anomaly detection (DB hiccup, backend unreachable) never breaks the
    core position-filtering response, which must stay reliable
    independent of anomaly detection's health. tag_offline is NOT checked
    here - see tag_offline_sweep.py for why that one needs a timer instead.
    """
    kf = registry.get(reading.tag_id)
    x, y, accuracy_m = kf.update(reading.x_meas, reading.y_meas, reading.timestamp, reading.confidence)
    logger.info("filtered position tag=%s accuracy_m=%.2f", reading.tag_id, accuracy_m)

    try:
        restricted = await zone_repo.find_restricted_zone_containing(x, y)
        zone_id = restricted["zone_id"] if restricted else None
        if _zone_breach_state.check_entry(reading.tag_id, zone_id):
            employee_id = await zone_repo.get_tag_employee(reading.tag_id)
            await report_anomaly(
                alert_type="zone_breach",
                bearer_token=user.raw_token,
                employee_id=employee_id,
                tag_id=reading.tag_id,
                zone_id=zone_id,
                details={"zone_name": restricted["name"], "x": x, "y": y},
            )
    except Exception:
        logger.exception(
            "zone_breach check failed for tag=%s (position filtering still succeeded)", reading.tag_id
        )

    try:
        if _inactivity_state.check_inactivity(reading.tag_id, x, y, time.time(), INACTIVITY_THRESHOLD_SECONDS):
            employee_id = await zone_repo.get_tag_employee(reading.tag_id)
            await report_anomaly(
                alert_type="inactivity",
                bearer_token=user.raw_token,
                employee_id=employee_id,
                tag_id=reading.tag_id,
                details={"x": x, "y": y, "still_for_seconds": INACTIVITY_THRESHOLD_SECONDS},
            )
    except Exception:
        logger.exception(
            "inactivity check failed for tag=%s (position filtering still succeeded)", reading.tag_id
        )

    return FilteredPosition(tag_id=reading.tag_id, x=x, y=y, accuracy_m=accuracy_m)


# ---------------------------------------------------------------------------
# Fingerprinting (Section 5 - Train Mode)
# ---------------------------------------------------------------------------

class LabeledSampleIn(BaseModel):
    true_x: float
    true_y: float
    rssi: dict[str, float]
    timestamp: float
    badge_orientation: str = "unknown"


class TrainRequest(BaseModel):
    zone_id: str = Field(..., max_length=64)
    beacon_ids: list[str] = Field(..., min_length=1)
    samples: list[LabeledSampleIn] = Field(..., min_length=1)


class ValidationResult(BaseModel):
    n_train: int
    n_holdout: int
    mean_error_m: float
    p90_error_m: float
    max_error_m: float


@app.post(
    "/internal/fingerprint/train",
    response_model=ValidationResult,
    dependencies=[Depends(require_role("security_admin"))],
)
async def train_fingerprint_model(req: TrainRequest, user: AuthenticatedUser = Depends(get_current_user)):
    """Retrains the positioning model for a zone from a freshly collected
    Train Mode walk. Restricted to security_admin: retraining changes
    positioning accuracy for every employee tracked in this zone, so it is
    not something any manager role should be able to trigger casually.

    The model is validated against a held-out slice of THIS SAME walk
    before it can be saved (see FingerprintModel.save) - an unvalidated
    model is never deployed, per Section 5's "defensible in a review"
    requirement.
    """
    walk = TrainingWalk(zone_id=req.zone_id, beacon_ids=req.beacon_ids)
    for s in req.samples:
        walk.add_sample(LabeledSample(**s.model_dump()))

    model = FingerprintModel(beacon_ids=sorted(req.beacon_ids))
    report = model.fit_and_validate(walk)
    model.save(MODEL_DIR / req.zone_id)

    logger.info(
        "fingerprint model retrained zone=%s mean_error_m=%.2f by=%s",
        req.zone_id, report.mean_error_m, user.sub,
    )
    # Retraining is a system-level action, not tied to one employee, so
    # resource_id is None - still logged so there's a record of who
    # changed the live positioning model and when. actor_role comes from
    # the verified JWT, matching the user_role enum in schema.sql exactly.
    await log_action(
        actor_user_id=user.sub,
        actor_role="security_admin",
        action="model_retrain",
        resource_type="model",
        resource_id=req.zone_id,
        justification="train_mode_walk",
    )

    return ValidationResult(**report.as_dict())


class PredictRequest(BaseModel):
    zone_id: str = Field(..., max_length=64)
    rssi: dict[str, float]


class PredictResult(BaseModel):
    x: float
    y: float


@app.post("/internal/fingerprint/predict", response_model=PredictResult)
async def predict_position(req: PredictRequest, user: AuthenticatedUser = Depends(get_current_user)):
    model_path = MODEL_DIR / req.zone_id
    if not model_path.exists():
        raise HTTPException(status_code=404, detail=f"No trained model for zone '{req.zone_id}' yet")
    model = FingerprintModel.load(model_path)
    x, y = model.predict(req.rssi)
    return PredictResult(x=x, y=y)


# ---------------------------------------------------------------------------
# Checkpoint verification (Section 5 / checkpoint_events)
#
# Backend owns creating the checkpoint_events row (zone_id, tag_id,
# employee_id, photo_url) with match_status='pending'. This service
# generates a face embedding from the photo, compares it against enrolled
# employees, and PATCHes the result back via the backend's
# PATCH /checkpoints/{id}/match - it never writes to Postgres directly for
# this table (same single-write-path pattern as position_events).
#
# Ownership confirmed with Shashank: the backend, not this service, decides
# whether a result is a badge-sharing/tailgating signal (comparing
# match_employee_id/match_status against its own tag-assignment record and
# creating the alerts row itself). This service only ever reports the face
# match - it doesn't need the alerts schema or tag-assignment table at all.
# ---------------------------------------------------------------------------

_embedding_generator: EmbeddingGenerator = InsightFaceEmbeddingGenerator()
_enrolled_repo: EnrolledEmbeddingsRepository = PostgresEnrolledEmbeddings()


class CheckpointVerifyRequest(BaseModel):
    checkpoint_event_id: str
    zone_id: str
    photo_url: str


class CheckpointVerifyResult(BaseModel):
    checkpoint_event_id: str
    match_employee_id: Optional[str]
    match_confidence: Optional[float]
    match_status: str


@app.post(
    "/internal/checkpoint-verify",
    response_model=CheckpointVerifyResult,
    dependencies=[Depends(require_role("security_admin"))],
)
async def checkpoint_verify(
    req: CheckpointVerifyRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    async with httpx.AsyncClient(timeout=10.0) as client:
        photo_resp = await client.get(req.photo_url)
        photo_resp.raise_for_status()
        photo_bytes = photo_resp.content

    query_embedding = await _embedding_generator.generate(photo_bytes)
    enrolled = await _enrolled_repo.fetch_all()
    result = find_best_match(query_embedding, enrolled)

    await patch_checkpoint_match(
        checkpoint_event_id=req.checkpoint_event_id,
        result=result,
        service_token=user.raw_token,
    )

    # Every checkpoint verification touches an individual's data - logged
    # before returning, per Section 8. resource_id is the checkpoint event,
    # not the matched employee, since match_employee_id may be None.
    await log_action(
        actor_user_id=user.sub,
        actor_role="security_admin",
        action="checkpoint_verify",
        resource_type="checkpoint_events",
        resource_id=req.checkpoint_event_id,
        justification=f"zone={req.zone_id} status={result.match_status}",
    )

    return CheckpointVerifyResult(
        checkpoint_event_id=req.checkpoint_event_id,
        match_employee_id=result.match_employee_id,
        match_confidence=result.match_confidence,
        match_status=result.match_status,
    )


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
